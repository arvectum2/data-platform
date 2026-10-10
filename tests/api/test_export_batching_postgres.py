"""Real PostgreSQL regression for bounded-query, paginated collection export."""
from __future__ import annotations

import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event

from arvectum_data.api.config import Settings
from arvectum_data.api.service import DataPlatformService

pytestmark = pytest.mark.postgres


def test_export_queries_do_not_scale_with_resources():
    url = os.getenv("ARVECTUM_DATA_TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("ARVECTUM_DATA_TEST_DATABASE_URL is not configured")
    command.upgrade(Config("alembic.ini"), "head")
    service = DataPlatformService(Settings(
        environment="test", database_url=url,
        embedding_provider="hashing", embedding_model="export-batch", embedding_dimension=32,
    ))
    collection = "export-batch:" + uuid.uuid4().hex[:12]
    service.create_collection(collection_id=collection, owner="test", name="batch", default_language="russian")
    for i in range(6):
        service.ingest_document_bytes(
            collection_id=collection, filename=f"source-{i}.txt",
            canonical_uri=f"test://export/{i}",
            content=("Условия поставки и оплаты. " * 12 + str(i)).encode("utf-8"),
        )

    engine = service.session_factory.kw["bind"]
    calls: list[str] = []

    def on_query(connection, cursor, statement, parameters, context, executemany):
        calls.append(statement)

    event.listen(engine, "before_cursor_execute", on_query)
    try:
        exported = service.export_collection(collection, include_content=True)
    finally:
        event.remove(engine, "before_cursor_execute", on_query)
    assert len(calls) <= 7, f"export issued {len(calls)} SQL statements for six resources"
    assert exported["total_resources"] == 6
    assert len(exported["resources"]) == 6
    # Resource order is by stable hash ID, not URI or original insertion time.
    assert {r["canonical_uri"] for r in exported["resources"]} == {
        f"test://export/{i}" for i in range(6)
    }
    assert [r["resource_id"] for r in exported["resources"]] == sorted(
        r["resource_id"] for r in exported["resources"]
    )
    assert all(r["documents"] and r["documents"][0]["chunks"] for r in exported["resources"])
    assert service.export_collection(collection, offset=4, limit=2)["has_more"] is False
    assert service.export_collection(collection, offset=0, limit=2)["has_more"] is True

    calls.clear()
    event.listen(engine, "before_cursor_execute", on_query)
    try:
        metadata_export = service.export_collection(collection, include_content=False)
    finally:
        event.remove(engine, "before_cursor_execute", on_query)
    assert len(calls) <= 7
    assert len(metadata_export["resources"]) == 6
    assert all(r["documents"][0]["text"] is None for r in metadata_export["resources"])
    assert all(r["documents"][0]["chunks"][0]["text"] is None for r in metadata_export["resources"])
    # Metadata-only SELECT statements must not fetch the heavy text columns.
    queries = " ".join(calls).lower()
    assert "documents.text" not in queries
    assert "chunks.text" not in queries
