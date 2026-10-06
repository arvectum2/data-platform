from __future__ import annotations

import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

from arvectum_data.api.app import create_app
from arvectum_data.api.config import Settings
from arvectum_data.storage.postgres import ConsumerApiKeyRow


pytestmark = pytest.mark.postgres


def _database_url() -> str:
    value = os.getenv("ARVECTUM_DATA_TEST_DATABASE_URL", "").strip()
    if not value:
        pytest.skip("ARVECTUM_DATA_TEST_DATABASE_URL is not configured")
    return value


def test_managed_consumer_key_issue_rotate_revoke_and_external_search() -> None:
    database_url = _database_url()
    os.environ["ARVECTUM_DATA_DATABASE_URL"] = database_url
    command.upgrade(Config("alembic.ini"), "head")

    app = create_app(
        Settings(
            environment="test",
            log_level="WARNING",
            database_url=database_url,
            internal_api_key="admin-secret",
            embedding_provider="hashing",
            embedding_model="auth-hash",
            embedding_dimension=32,
        )
    )
    client = TestClient(app)
    admin = {"X-Arvectum-Key": "admin-secret"}
    collection_id = f"auth:{uuid.uuid4().hex[:12]}"
    consumer_id = f"external-{uuid.uuid4().hex[:8]}"

    created = client.post(
        "/v1/collections",
        headers=admin,
        json={
            "collection_id": collection_id,
            "owner": "external-test",
            "name": "External auth test",
            "access_policy": {"tenant_id": "tenant-external"},
        },
    )
    assert created.status_code == 200

    ingested = client.post(
        "/v1/ingest/document",
        headers=admin,
        data={
            "collection_id": collection_id,
            "canonical_uri": "benchmark://auth/evidence",
            "pre_chunked": "true",
        },
        files={
            "file": (
                "evidence.txt",
                b"managed key external search evidence",
                "text/plain",
            )
        },
    )
    assert ingested.status_code == 200

    issued = client.post(
        "/v1/auth/consumer-keys",
        headers=admin,
        json={
            "consumer_id": consumer_id,
            "tenant_id": "tenant-external",
            "label": "integration",
        },
    )
    assert issued.status_code == 200
    issued_body = issued.json()
    secret = issued_body["secret"]
    assert secret.startswith("avk_")
    assert issued_body["key_prefix"] == secret[:12]
    key_id = issued_body["key_id"]

    with app.state.platform_service._require_factory()() as session:
        row = session.scalar(
            select(ConsumerApiKeyRow).where(
                ConsumerApiKeyRow.key_id == key_id
            )
        )
        assert row is not None
        assert row.key_hash != secret
        assert len(row.key_hash) == 64

    listed = client.get(
        f"/v1/auth/consumer-keys?consumer_id={consumer_id}",
        headers=admin,
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert "secret" not in listed.json()[0]

    consumer_headers = {
        "X-Arvectum-Consumer": consumer_id,
        "X-Arvectum-Consumer-Key": secret,
    }
    search = client.post(
        "/v1/search",
        headers={**consumer_headers, "X-Request-ID": "usage-retry-search"},
        json={
            "query": "managed key external search evidence",
            "collections": [collection_id],
            "limit": 5,
            "mode": "lexical",
        },
    )
    assert search.status_code == 200
    assert search.json()["hits"][0]["canonical_uri"] == "benchmark://auth/evidence"

    usage_retry = client.post(
        "/v1/search",
        headers={**consumer_headers, "X-Request-ID": "usage-retry-search"},
        json={
            "query": "managed key external search evidence",
            "collections": [collection_id],
            "limit": 5,
            "mode": "lexical",
        },
    )
    assert usage_retry.status_code == 200

    admin_denied = client.get(
        "/v1/collections",
        headers=consumer_headers,
    )
    assert admin_denied.status_code == 401

    rotated = client.post(
        f"/v1/auth/consumer-keys/{key_id}/rotate",
        headers=admin,
    )
    assert rotated.status_code == 200
    rotated_body = rotated.json()
    new_secret = rotated_body["secret"]
    assert new_secret != secret

    old_denied = client.post(
        "/v1/search",
        headers=consumer_headers,
        json={
            "query": "evidence",
            "collections": [collection_id],
            "mode": "lexical",
        },
    )
    assert old_denied.status_code == 403

    new_headers = {
        "X-Arvectum-Consumer": consumer_id,
        "X-Arvectum-Consumer-Key": new_secret,
    }
    new_allowed = client.post(
        "/v1/search",
        headers=new_headers,
        json={
            "query": "evidence",
            "collections": [collection_id],
            "mode": "lexical",
        },
    )
    assert new_allowed.status_code == 200

    revoked = client.post(
        f"/v1/auth/consumer-keys/{rotated_body['key_id']}/revoke",
        headers=admin,
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"

    revoked_denied = client.post(
        "/v1/search",
        headers=new_headers,
        json={
            "query": "evidence",
            "collections": [collection_id],
            "mode": "lexical",
        },
    )
    assert revoked_denied.status_code == 403

    usage = client.get(
        f"/v1/usage/summary?consumer_id={consumer_id}",
        headers=admin,
    )
    assert usage.status_code == 200
    usage_body = usage.json()
    assert usage_body["total_events"] == 2
    assert usage_body["total_quantity"] == 2
    assert usage_body["billable_quantity"] == 2
    assert usage_body["buckets"] == [
        {
            "tenant_id": "tenant-external",
            "consumer_id": consumer_id,
            "operation": "search",
            "unit": "request",
            "events": 2,
            "quantity": 2,
            "billable_quantity": 2,
        }
    ]
