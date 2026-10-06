from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from arvectum_data.api.app import create_app
from arvectum_data.api.config import Settings
from arvectum_data.storage.postgres import ResourceRow


pytestmark = pytest.mark.postgres


def _database_url() -> str:
    value = os.getenv("ARVECTUM_DATA_TEST_DATABASE_URL", "").strip()
    if not value:
        pytest.skip("ARVECTUM_DATA_TEST_DATABASE_URL is not configured")
    return value


def test_collection_export_retention_and_confirmed_delete() -> None:
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
            embedding_model="lifecycle-hash",
            embedding_dimension=32,
        )
    )
    client = TestClient(app)
    headers = {"X-Arvectum-Key": "test-secret"}
    collection_id = f"lifecycle:{uuid.uuid4().hex[:12]}"

    created = client.post(
        "/v1/collections",
        headers=headers,
        json={
            "collection_id": collection_id,
            "owner": "tests",
            "name": "Lifecycle test",
            "retention_policy": {"max_age_days": 30},
        },
    )
    assert created.status_code == 200
    assert created.json()["retention_policy"] == {"max_age_days": 30}

    content = b"lifecycle retention export evidence"
    ingested = client.post(
        "/v1/ingest/document",
        headers=headers,
        data={
            "collection_id": collection_id,
            "canonical_uri": "benchmark://lifecycle/old",
            "pre_chunked": "true",
        },
        files={"file": ("old.txt", content, "text/plain")},
    )
    assert ingested.status_code == 200
    resource_id = ingested.json()["resource_id"]

    metadata_export = client.get(
        f"/v1/collections/{collection_id}/export",
        headers=headers,
    )
    assert metadata_export.status_code == 200
    exported = metadata_export.json()
    assert exported["total_resources"] == 1
    assert exported["resources"][0]["documents"][0]["text"] is None
    assert exported["resources"][0]["documents"][0]["chunks"][0]["text"] is None

    content_export = client.get(
        f"/v1/collections/{collection_id}/export?include_content=true",
        headers=headers,
    )
    assert content_export.status_code == 200
    exported_text = content_export.json()["resources"][0]["documents"][0]["text"]
    assert "lifecycle retention export evidence" in exported_text

    service = app.state.platform_service
    with service._require_factory()() as session:
        resource = session.get(ResourceRow, resource_id)
        assert resource is not None
        resource.last_seen_at = datetime.now(UTC) - timedelta(days=60)
        session.add(resource)
        session.commit()

    preview = client.post(
        f"/v1/collections/{collection_id}/retention/prune",
        headers=headers,
    )
    assert preview.status_code == 200
    assert preview.json()["dry_run"] is True
    assert preview.json()["matched_resources"] == 1
    assert preview.json()["deleted_resources"] == 0

    still_present = client.get(
        f"/v1/collections/{collection_id}/stats",
        headers=headers,
    )
    assert still_present.json()["resources"] == 1

    pruned = client.post(
        f"/v1/collections/{collection_id}/retention/prune?dry_run=false",
        headers=headers,
    )
    assert pruned.status_code == 200
    assert pruned.json()["deleted_resources"] == 1

    after_prune = client.get(
        f"/v1/collections/{collection_id}/stats",
        headers=headers,
    )
    assert after_prune.status_code == 200
    assert after_prune.json()["resources"] == 0
    assert after_prune.json()["documents"] == 0
    assert after_prune.json()["chunks"] == 0
    assert after_prune.json()["embeddings"] == 0

    second = client.post(
        "/v1/ingest/document",
        headers=headers,
        data={
            "collection_id": collection_id,
            "canonical_uri": "benchmark://lifecycle/new",
            "pre_chunked": "true",
        },
        files={"file": ("new.txt", b"new retained evidence", "text/plain")},
    )
    assert second.status_code == 200

    delete_preview = client.delete(
        f"/v1/collections/{collection_id}",
        headers=headers,
    )
    assert delete_preview.status_code == 200
    assert delete_preview.json()["deleted"] is False
    assert delete_preview.json()["counts"]["resources"] == 1
    assert client.get(
        f"/v1/collections/{collection_id}",
        headers=headers,
    ).status_code == 200

    deleted = client.delete(
        f"/v1/collections/{collection_id}?confirm=true",
        headers=headers,
    )
    assert deleted.status_code == 200
    assert deleted.json()["confirmed"] is True
    assert deleted.json()["deleted"] is True
    assert client.get(
        f"/v1/collections/{collection_id}",
        headers=headers,
    ).status_code == 404
