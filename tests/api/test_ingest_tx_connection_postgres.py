"""Isolated PostgreSQL connection-lifetime + atomic ingest regression.

Only the CI's explicit TEST_DATABASE_URL is touched. All content is generated,
the synthetic collection has a unique ID and is deleted after the test.
No production service, model endpoint or customer source is accessed.
"""
from __future__ import annotations

import os
import uuid
from urllib.parse import urlsplit

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.orm import sessionmaker

from arvectum_data.api.config import Settings
from arvectum_data.api.service import DataPlatformService
from arvectum_data.documents import ingest_bytes
from arvectum_data.indexing.embeddings import BaseEmbeddingProvider
from arvectum_data.storage.postgres import (
    ChunkEmbeddingRow,
    CollectionRow,
    DocumentRow,
    ResourceRow,
)

pytestmark = pytest.mark.postgres


class SyntheticPostgresEmbedding(BaseEmbeddingProvider):
    provider_name = "synthetic_pg_lifetime"
    model_name = "synthetic_pool_probe_v1"
    dimension = 16

    def __init__(self, engine):
        self.engine = engine
        self.calls = 0
        self.pool_occupancy_at_call = []

    def embed_texts(self, texts):
        self.calls += 1
        self.pool_occupancy_at_call.append(self.engine.pool.checkedout())
        # With pool_size=1 and max_overflow=0 this independent DB query would
        # timeout if _persist_and_index held its SQL connection during embedding.
        with self.engine.connect() as independent:
            assert independent.scalar(text("SELECT 1")) == 1
        return [[float(i + 1) / 16 for i in range(16)] for _ in texts]


class UnavailableSyntheticEmbedding(SyntheticPostgresEmbedding):
    def embed_texts(self, _texts):
        assert self.engine.pool.checkedout() == 0
        raise RuntimeError("mocked embedding outage")


def test_single_connection_pool_released_during_inference_and_ingest_atomic():
    database_url = os.getenv("ARVECTUM_DATA_TEST_DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip("ARVECTUM_DATA_TEST_DATABASE_URL not configured")
    # Fail closed on remote/server-style accidental targets. CI uses a local
    # ephemeral service, not an externally routable database.
    host = urlsplit(database_url).hostname
    if host not in {"127.0.0.1", "localhost", "::1", "postgres"}:
        pytest.skip("PostgreSQL test requires the isolated local CI service")

    previous = os.environ.get("ARVECTUM_DATA_DATABASE_URL")
    os.environ["ARVECTUM_DATA_DATABASE_URL"] = database_url
    try:
        command.upgrade(Config("alembic.ini"), "head")
    finally:
        if previous is None:
            os.environ.pop("ARVECTUM_DATA_DATABASE_URL", None)
        else:
            os.environ["ARVECTUM_DATA_DATABASE_URL"] = previous

    engine = create_engine(database_url, pool_size=1, max_overflow=0, pool_timeout=0.1)
    factory = sessionmaker(bind=engine)
    collection_id = f"synthetic:pg-pool:{uuid.uuid4().hex}"
    provider = SyntheticPostgresEmbedding(engine)
    try:
        settings = Settings(
            _env_file=None,
            environment="test",
            cross_encoder_provider="disabled",
            reasoning_policy="disabled",
            vision_policy="disabled",
            embedding_inference_batch_size=8,
            embedding_retry_max_attempts=1,
        )
        service = DataPlatformService(
            settings,
            session_factory=factory,
            embedding_provider=provider,
        )
        service.create_collection(
            collection_id=collection_id,
            owner="synthetic-integration-only",
            name="Synthetic PG pool test",
            default_language="simple",
        )
        ingest = ingest_bytes(
            b"synthetic isolated postgres ingest generated text " * 10,
            filename="synthetic-test.txt",
            collection_id=collection_id,
            canonical_uri="synthetic://pg/lifetime/first",
            title="synthetic pg test",
        )
        first = service._persist_and_index(ingest)
        assert first["embeddings_written"] == first["chunks"]
        assert first["embeddings_skipped_existing"] == 0
        assert provider.calls > 0
        assert provider.pool_occupancy_at_call == [0] * provider.calls
        assert engine.pool.checkedout() == 0

        # Exactly the same synthetic provenance must reuse existing vectors.
        second = service._persist_and_index(ingest)
        assert second["resource_id"] == first["resource_id"]
        assert second["document_id"] == first["document_id"]
        assert second["embeddings_written"] == 0
        assert second["embeddings_skipped_existing"] == first["chunks"]
        assert len(provider.pool_occupancy_at_call) == provider.calls
        assert engine.pool.checkedout() == 0

        failing = DataPlatformService(
            settings,
            session_factory=factory,
            embedding_provider=UnavailableSyntheticEmbedding(engine),
        )
        another = ingest_bytes(
            b"synthetic isolated postgres failing inference content " * 10,
            filename="synthetic-test.txt",
            collection_id=collection_id,
            canonical_uri="synthetic://pg/lifetime/model-fails",
            title="synthetic failure",
        )
        with pytest.raises(RuntimeError, match="mocked embedding outage"):
            failing._persist_and_index(another)

        with factory() as session:
            assert session.get(ResourceRow, ingest.resource.resource_id) is not None
            assert session.get(DocumentRow, ingest.document.document_id) is not None
            assert session.get(ResourceRow, another.resource.resource_id) is None
            expected = session.scalar(
                select(func.count()).select_from(ChunkEmbeddingRow).where(
                    ChunkEmbeddingRow.chunk_id.in_([chunk.chunk_id for chunk in ingest.chunks]),
                    ChunkEmbeddingRow.provider == provider.provider_name,
                    ChunkEmbeddingRow.model == provider.model_name,
                )
            )
            assert expected == first["embeddings_written"]
    finally:
        # Delete only the unique synthetic collection. PostgreSQL CASCADE FKs
        # remove its generated children; never call remote services.
        with engine.begin() as connection:
            connection.execute(
                delete(CollectionRow).where(CollectionRow.collection_id == collection_id)
            )
        engine.dispose()
