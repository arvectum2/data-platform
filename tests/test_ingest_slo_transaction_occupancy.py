"""Prove an independent SQL connection is available during mocked inference.

This has a one-connection in-memory SQLite pool. It verifies session lifetime
and rollback/commit behavior without production data, live model or network.
It does NOT prove that this is the cause of production ingest P95.
"""
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from arvectum_data.api.config import Settings
from arvectum_data.api.service import DataPlatformService
from arvectum_data.storage.postgres import CollectionRow, DataRepository


class SyntheticBlockedPoolProbe:
    provider_name = "synthetic_proof"
    model_name = "synthetic_mock"
    dimension = 2

    def __init__(self, session_factory, engine):
        self.session_factory = session_factory
        self.engine = engine
        self.checked_out_during_embedding = -1
        self.other_client_unblocked = False
        self.called = 0

    def embed_texts(self, texts):
        self.called += 1
        self.checked_out_during_embedding = self.engine.pool.checkedout()
        with self.session_factory() as unrelated:
            self.other_client_unblocked = unrelated.execute(text("SELECT 1")).scalar_one() == 1
        return [[0.0, 1.0] for _ in texts]


def test_ingest_releases_sql_connection_during_unrelated_model_inference(
    monkeypatch,
):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=QueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.05,
        connect_args={"check_same_thread": False},
    )
    try:
        CollectionRow.__table__.create(engine)
        session_factory = sessionmaker(bind=engine)
        with session_factory() as init:
            init.add(
                CollectionRow(
                    collection_id="synthetic:pool:probe",
                    owner="synthetic",
                    name="Mock connection lifetime",
                    default_language="simple",
                    embedding_provider="synthetic_proof",
                    embedding_model="synthetic_mock",
                    embedding_dimension=2,
                )
            )
            init.commit()

        provider = SyntheticBlockedPoolProbe(session_factory, engine)
        service = DataPlatformService(
            Settings(
                _env_file=None,
                environment="synthetic-test",
                cross_encoder_provider="disabled",
                reasoning_policy="disabled",
                vision_policy="disabled",
                embedding_inference_batch_size=8,
                embedding_retry_max_attempts=1,
            ),
            session_factory=session_factory,
            embedding_provider=provider,
        )
        # Only transaction/SQLAlchemy orchestration is real. No source or
        # embeddings are persisted; repository methods are intentionally inert.
        monkeypatch.setattr(
            DataRepository, "existing_embedding_chunk_ids",
            lambda *args, **kwargs: set(),
        )
        monkeypatch.setattr(DataRepository, "persist_ingest", lambda *args: None)
        monkeypatch.setattr(
            DataRepository, "upsert_embeddings",
            lambda *args, **kwargs: None,
        )

        synthetic = SimpleNamespace(
            resource=SimpleNamespace(
                collection_id="synthetic:pool:probe",
                resource_id="synthetic-resource",
                canonical_uri="synthetic://test-only",
            ),
            document=SimpleNamespace(
                document_id="synthetic-document",
                extraction_status="extracted",
            ),
            chunks=(SimpleNamespace(chunk_id="synthetic-chunk", text="synthetic only"),),
        )
        response = service._persist_and_index(synthetic)
        assert response["embedding_attempts"] == 1
        assert provider.called == 1
        assert provider.checked_out_during_embedding == 0
        assert provider.other_client_unblocked is True
        assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()
