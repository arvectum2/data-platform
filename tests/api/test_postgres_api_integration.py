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

    client = TestClient(
        create_app(
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
    )
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
        data={"collection_id": "api:docs"},
        files={"file": ("cable.txt", content, "text/plain")},
    )
    assert ingested.status_code == 200
    assert ingested.json()["chunks"] > 0
    assert ingested.json()["embeddings"] == ingested.json()["chunks"]

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
    assert hits[0]["evidence"][0]["canonical_uri"] == "upload://cable.txt"

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

    missing_scope = client.post(
        "/v1/search",
        headers=headers,
        json={
            "query": "силовой кабель",
            "collections": ["api:missing"],
        },
    )
    assert missing_scope.status_code == 404
