"""Compare federation to per-collection execution on a real pgvector database."""
from __future__ import annotations

import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event

from arvectum_data.api.config import Settings
from arvectum_data.api.service import DataPlatformService
from arvectum_data.search import PostgresSearchBackend
from arvectum_data.storage.postgres import DataRepository

pytestmark = pytest.mark.postgres


def test_federated_postgres_search_preserves_legacy_order_and_reduces_roundtrips():
    url = os.getenv("ARVECTUM_DATA_TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("ARVECTUM_DATA_TEST_DATABASE_URL is not configured")
    command.upgrade(Config("alembic.ini"), "head")
    service = DataPlatformService(Settings(
        environment="test", database_url=url, embedding_provider="hashing",
        embedding_model="federated-contract-test", embedding_dimension=32,
    ))
    collection_ids = []
    for language in ("russian", "english", "russian", "english", "simple", "russian"):
        collection = "federation:" + uuid.uuid4().hex[:12]
        collection_ids.append(collection)
        service.create_collection(
            collection_id=collection, name="Search", owner="test", default_language=language,
        )
        for index in range(3):
            service.ingest_document_bytes(
                collection_id=collection, filename=f"{index}.txt",
                canonical_uri=f"test://{collection}/{index}",
                content=((
                    f"Contract agreement and delivery terms reference {index}. "
                    "Договор на поставку оборудования и ответственность сторон. "
                ) * (20 + index)).encode(),
            )
    engine = service.session_factory.kw["bind"]
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    with service.session_factory() as session:
        repo = DataRepository(session)
        backend = PostgresSearchBackend(repo)
        query_vector = service.embedding_provider.embed_query("contract agreement")
        for mode in ("lexical", "vector"):
            for limit in (1, 5, 15):
                if mode == "lexical":
                    historical = []
                    for collection in collection_ids:
                        for item in repo.search_lexical(
                            "contract", collection_id=collection, limit=limit,
                        ):
                            historical.append((collection, item))
                    historical.sort(key=lambda pair: (-pair[1].score, pair[1].chunk_id))
                else:
                    historical = []
                    for collection in collection_ids:
                        for item in repo.search_vectors(
                            query_vector, collection_id=collection,
                            provider=service.embedding_provider.provider_name,
                            model=service.embedding_provider.model_name,
                            limit=limit,
                        ):
                            historical.append((collection, item))
                    historical.sort(key=lambda pair: (-pair[1].score, pair[1].chunk_id))
                expected = historical[:limit]
                statements.clear()
                event.listen(engine, "before_cursor_execute", capture)
                try:
                    if mode == "lexical":
                        actual = backend.search_lexical(
                            "contract", collections=collection_ids, filters=None, limit=limit,
                        )
                    else:
                        actual = backend.search_vector(
                            query_vector, collections=collection_ids, filters=None,
                            provider=service.embedding_provider.provider_name,
                            model=service.embedding_provider.model_name,
                            limit=limit,
                        )
                finally:
                    event.remove(engine, "before_cursor_execute", capture)
                assert [item.chunk_id for item in actual] == [item.chunk_id for _, item in expected]
                assert [item.score for item in actual] == pytest.approx(
                    [item.score for _, item in expected]
                )
                assert [item.metadata["collection_id"] for item in actual] == [
                    collection for collection, _ in expected
                ]
                if mode == "lexical":
                    # 1 lookup of collection language + up to 3 ranked
                    # SELECTs, instead of six per-collection searches.
                    assert len(statements) <= 4, statements
                else:
                    assert len(statements) == 1, statements


def test_federation_respects_resource_filter_without_cross_collection_leak():
    url = os.getenv("ARVECTUM_DATA_TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("ARVECTUM_DATA_TEST_DATABASE_URL is not configured")
    command.upgrade(Config("alembic.ini"), "head")
    service = DataPlatformService(Settings(
        environment="test", database_url=url, embedding_provider="hashing",
        embedding_model="federated-filter", embedding_dimension=32,
    ))
    ids = []
    resources = []
    for _ in range(3):
        col = "filtered:" + uuid.uuid4().hex[:12]
        ids.append(col)
        service.create_collection(
            collection_id=col, name="Filter", owner="test", default_language="english",
        )
        ingested = service.ingest_document_bytes(
            collection_id=col, filename="doc.txt",
            canonical_uri=f"test://filtered/{col}",
            content=("Contract agreement delivery and payment terms. " * 35).encode(),
        )
        resources.append(ingested["resource_id"])
    with service.session_factory() as session:
        repo = DataRepository(session)
        backend = PostgresSearchBackend(repo)
        filters = {"resource_id": (resources[1],)}
        lexical = backend.search_lexical(
            "contract", collections=ids, filters=filters, limit=20,
        )
        vector = backend.search_vector(
            service.embedding_provider.embed_query("contract"),
            collections=ids, filters=filters, limit=20,
            provider=service.embedding_provider.provider_name,
            model=service.embedding_provider.model_name,
        )
        for hits in (lexical, vector):
            assert hits
            assert {hit.resource_id for hit in hits} == {resources[1]}
            assert {hit.metadata["collection_id"] for hit in hits} == {ids[1]}
