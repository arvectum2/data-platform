"""Performance correctness gates on disposable PostgreSQL with pgvector."""
from __future__ import annotations

import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, select

from arvectum_data.api.config import Settings
from arvectum_data.api.service import DataPlatformService
from arvectum_data.api.service_support import EmbeddingContractMismatch
from arvectum_data.storage.postgres import DataRepository
from arvectum_data.search import SearchMode, SearchQuery
from arvectum_data.storage.postgres import (
    ChunkEmbeddingRow, ChunkRow, DocumentRow, ResourceRow,
)

pytestmark = pytest.mark.postgres


def _service():
    url = os.getenv("ARVECTUM_DATA_TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("ARVECTUM_DATA_TEST_DATABASE_URL is not configured")
    command.upgrade(Config("alembic.ini"), "head")
    return DataPlatformService(Settings(
        environment="test", database_url=url,
        embedding_provider="hashing", embedding_model="optimization-hash", embedding_dimension=32,
    ))


def _listen(service, statements):
    engine = service.session_factory.kw["bind"]

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", capture)
    return engine, capture


def test_bulk_embedding_write_and_revision_projections():
    service = _service()
    collection = "bulk-opt:" + uuid.uuid4().hex[:12]
    service.create_collection(
        collection_id=collection, owner="test", name="Bulk indexing", default_language="russian"
    )
    seen = []
    engine, capture = _listen(service, seen)
    try:
        ingested = service.ingest_document_bytes(
            collection_id=collection,
            filename="many-chunks.txt",
            canonical_uri="test://bulk-index/many",
            content=("Условия поставки, качество и оплата товаров на складе. " * 1400).encode(),
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert ingested["chunks"] >= 5
    embedding_inserts = [s for s in seen if s.lstrip().startswith("insert") and "dp_chunk_embeddings" in s]
    assert len(embedding_inserts) == 1, f"expected one batched INSERT, got {len(embedding_inserts)}"

    with service.session_factory() as session:
        original_ids = dict(session.execute(
            select(ChunkEmbeddingRow.chunk_id, ChunkEmbeddingRow.embedding_id)
            .join(ChunkRow, ChunkRow.chunk_id == ChunkEmbeddingRow.chunk_id)
            .join(DocumentRow, DocumentRow.document_id == ChunkRow.document_id)
            .join(ResourceRow, ResourceRow.resource_id == DocumentRow.resource_id)
            .where(ResourceRow.collection_id == collection)
        ).all())
    assert len(original_ids) == ingested["chunks"]

    seen.clear()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        job = service.rebuild_index(collection)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert job["status"] == "completed"
    assert job["metrics"]["embeddings_written"] == ingested["chunks"]
    embedding_inserts = [s for s in seen if s.lstrip().startswith("insert") and "dp_chunk_embeddings" in s]
    assert len(embedding_inserts) == 1
    chunk_reads = [s for s in seen if s.lstrip().startswith("select") and "dp_chunks" in s and "dp_chunks.text" in s]
    assert len(chunk_reads) == 1, "revision scans should not load full chunk text"

    with service.session_factory() as session:
        ids_after = dict(session.execute(
            select(ChunkEmbeddingRow.chunk_id, ChunkEmbeddingRow.embedding_id)
            .join(ChunkRow, ChunkRow.chunk_id == ChunkEmbeddingRow.chunk_id)
            .join(DocumentRow, DocumentRow.document_id == ChunkRow.document_id)
            .join(ResourceRow, ResourceRow.resource_id == DocumentRow.resource_id)
            .where(ResourceRow.collection_id == collection)
        ).all())
    assert ids_after == original_ids
    seen.clear()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        repeat = service.rebuild_index(collection)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert repeat["run_id"] == job["run_id"]
    assert not any("dp_chunks.text" in s for s in seen)


def test_multi_collection_authorization_uses_single_select():
    service = _service()
    collections = ["search-opt:" + uuid.uuid4().hex[:12] for _ in range(6)]
    for collection in collections:
        service.create_collection(
            collection_id=collection, owner="test", name="Batch authorization",
            default_language="russian",
        )
    seen = []
    engine, capture = _listen(service, seen)
    try:
        assert service.search(SearchQuery(
            query="закупка", collections=tuple(collections), mode=SearchMode.LEXICAL,
        )) == []
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    collection_selects = [s for s in seen if s.lstrip().startswith("select") and "from dp_collections" in s]
    assert len(collection_selects) == 1, collection_selects


def test_invalid_embedding_dimension_aborts_ingest_transaction():
    service = _service()
    collection = "invalid-dim:" + uuid.uuid4().hex[:12]
    service.create_collection(
        collection_id=collection, owner="test", name="Reject mixed vectors",
        default_language="russian",
    )
    original_provider = service.embedding_provider

    class BadProvider:
        provider_name = original_provider.provider_name
        model_name = original_provider.model_name
        dimension = original_provider.dimension

        def embed_texts(self, texts):
            return [[0.1] * (self.dimension - index % 2) for index, _ in enumerate(texts)]

    service.embedding_provider = BadProvider()
    with pytest.raises(EmbeddingContractMismatch, match="inconsistent dimensions"):
        service.ingest_document_bytes(
            collection_id=collection, filename="inconsistent.txt",
            canonical_uri="test://bad-vectors",
            content=("Условия поставки и возврата. " * 900).encode(),
        )
    with service.session_factory() as session:
        assert DataRepository(session).collection_chunk_count(collection) == 0
