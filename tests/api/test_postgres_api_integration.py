from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from arvectum_data.api.app import create_app
from arvectum_data.api.config import Settings


pytestmark = pytest.mark.postgres


def _database_url() -> str:
    value = os.getenv("ARVECTUM_DATA_TEST_DATABASE_URL", "").strip()
    if not value:
        pytest.skip("ARVECTUM_DATA_TEST_DATABASE_URL is not configured")
    return value


def test_http_collection_ingest_and_hybrid_search() -> None:
    database_url = _database_url()
    os.environ["ARVECTUM_DATA_DATABASE_URL"] = database_url
    command.upgrade(Config("alembic.ini"), "head")

    app = create_app(
        Settings(
            environment="test",
            log_level="WARNING",
            database_url=database_url,
            internal_api_key="test-secret",
            embedding_provider="hashing",
            embedding_model="api-test-hash",
            embedding_dimension=64,
        )
    )
    client = TestClient(app)
    headers = {"X-Arvectum-Key": "test-secret"}

    created = client.post(
        "/v1/collections",
        headers=headers,
        json={
            "collection_id": "api:docs",
            "owner": "tests",
            "name": "API documents",
            "default_language": "russian",
        },
    )
    assert created.status_code == 200

    content = (
        "Силовой кабель ВВГнг предназначен для промышленного объекта. " * 80
    ).encode("utf-8")
    ingested = client.post(
        "/v1/ingest/document",
        headers=headers,
        data={
            "collection_id": "api:docs",
            "canonical_uri": "external-document://cable-1",
            "pre_chunked": "true",
        },
        files={"file": ("cable.txt", content, "text/plain")},
    )
    assert ingested.status_code == 200
    assert ingested.json()["canonical_uri"] == "external-document://cable-1"
    assert ingested.json()["chunks"] > 0
    assert ingested.json()["embeddings"] == ingested.json()["chunks"]
    assert ingested.json()["embeddings_written"] == ingested.json()["chunks"]
    assert ingested.json()["embeddings_skipped_existing"] == 0

    repeated = client.post(
        "/v1/ingest/document",
        headers=headers,
        data={
            "collection_id": "api:docs",
            "canonical_uri": "external-document://cable-1",
            "pre_chunked": "true",
        },
        files={"file": ("cable.txt", content, "text/plain")},
    )
    assert repeated.status_code == 200
    assert repeated.json()["resource_id"] == ingested.json()["resource_id"]
    assert repeated.json()["document_id"] == ingested.json()["document_id"]
    assert repeated.json()["chunks"] == ingested.json()["chunks"]
    assert repeated.json()["embeddings"] == ingested.json()["embeddings"]
    assert repeated.json()["embeddings_written"] == 0
    assert (
        repeated.json()["embeddings_skipped_existing"]
        == ingested.json()["embeddings"]
    )

    stats = client.get(
        "/v1/collections/api:docs/stats",
        headers=headers,
    )
    assert stats.status_code == 200
    assert stats.json()["resources"] == 1
    assert stats.json()["documents"] == 1
    assert stats.json()["chunks"] == ingested.json()["chunks"]
    assert stats.json()["embeddings"] == ingested.json()["embeddings"]
    assert stats.json()["first_seen_at"] is not None
    assert stats.json()["last_seen_at"] is not None
    assert stats.json()["latest_embedding_at"] is not None

    status = client.get("/v1/status", headers=headers)
    assert status.status_code == 200
    metrics = status.json()["metrics"]
    assert metrics["collections"] >= 1
    assert metrics["resources"] >= 1
    assert metrics["documents"] >= 1
    assert metrics["chunks"] >= 1
    assert metrics["embeddings"] >= 1

    searched = client.post(
        "/v1/search",
        headers=headers,
        json={
            "query": "силовой кабель",
            "collections": ["api:docs"],
            "mode": "hybrid",
            "limit": 5,
        },
    )
    assert searched.status_code == 200
    hits = searched.json()["hits"]
    assert hits
    assert hits[0]["scores"]["lexical"] is not None
    assert hits[0]["scores"]["vector"] is not None
    assert hits[0]["evidence"][0]["canonical_uri"] == "external-document://cable-1"

    rebuilt = client.post(
        "/v1/index/rebuild",
        headers=headers,
        json={"collection_id": "api:docs"},
    )
    assert rebuilt.status_code == 200
    job = rebuilt.json()
    assert job["status"] == "completed"
    assert job["metrics"]["chunks_seen"] > 0
    assert job["metrics"]["embeddings_written"] == job["metrics"]["chunks_seen"]

    fetched_job = client.get(
        f"/v1/index/jobs/{job['run_id']}",
        headers=headers,
    )
    assert fetched_job.status_code == 200
    assert fetched_job.json()["revision"] == job["revision"]

    repeated_rebuild = client.post(
        "/v1/index/rebuild",
        headers=headers,
        json={"collection_id": "api:docs"},
    )
    assert repeated_rebuild.status_code == 200
    repeated_job = repeated_rebuild.json()
    assert repeated_job["run_id"] == job["run_id"]
    assert repeated_job["revision"] == job["revision"]
    assert repeated_job["status"] == "completed"
    assert repeated_job["metrics"] == job["metrics"]

    stats_after_rebuild = client.get(
        "/v1/collections/api:docs/stats",
        headers=headers,
    )
    assert stats_after_rebuild.status_code == 200
    assert stats_after_rebuild.json()["active_index_revision"] == job["revision"]

    second_content = (
        "Дополнительные требования к монтажу силового кабеля. " * 20
    ).encode("utf-8")
    second_ingest = client.post(
        "/v1/ingest/document",
        headers=headers,
        data={
            "collection_id": "api:docs",
            "canonical_uri": "external-document://cable-2",
            "pre_chunked": "true",
        },
        files={"file": ("cable-2.txt", second_content, "text/plain")},
    )
    assert second_ingest.status_code == 200

    original_provider = app.state.platform_service.embedding_provider

    class FailingEmbeddingProvider:
        provider_name = original_provider.provider_name
        model_name = original_provider.model_name
        dimension = original_provider.dimension

        def embed_texts(self, texts):
            raise RuntimeError("synthetic embedding failure")

        def embed_query(self, text):
            raise RuntimeError("synthetic embedding failure")

    app.state.platform_service.embedding_provider = FailingEmbeddingProvider()
    failed_rebuild = client.post(
        "/v1/index/rebuild",
        headers=headers,
        json={"collection_id": "api:docs"},
    )
    assert failed_rebuild.status_code == 500
    app.state.platform_service.embedding_provider = original_provider

    stats_after_failure = client.get(
        "/v1/collections/api:docs/stats",
        headers=headers,
    )
    assert stats_after_failure.status_code == 200
    assert stats_after_failure.json()["active_index_revision"] == job["revision"]

    jobs_after_failure = app.state.platform_service.list_index_jobs(
        collection_id="api:docs"
    )
    assert jobs_after_failure[0]["status"] == "failed"
    assert jobs_after_failure[0]["revision"] != job["revision"]
    assert jobs_after_failure[0]["metrics"]["error_type"] == "RuntimeError"

    missing_scope = client.post(
        "/v1/search",
        headers=headers,
        json={
            "query": "силовой кабель",
            "collections": ["api:missing"],
        },
    )
    assert missing_scope.status_code == 404
