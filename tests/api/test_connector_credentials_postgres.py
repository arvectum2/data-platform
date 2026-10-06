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
from arvectum_data.api.service import DataPlatformService
from arvectum_data.connectors import (
    ConnectorHealth,
    ConnectorRegistry,
    ConnectorState,
    DiscoveryPage,
    DiscoveredResource,
)
from arvectum_data.indexing import HashingEmbeddingProvider
from arvectum_data.storage.postgres import ConnectorCredentialRow


pytestmark = pytest.mark.postgres


def _database_url() -> str:
    value = os.getenv("ARVECTUM_DATA_TEST_DATABASE_URL", "").strip()
    if not value:
        pytest.skip("ARVECTUM_DATA_TEST_DATABASE_URL is not configured")
    return value


class CredentialAwareTestConnector:
    name = "credential-test"

    def __init__(self, token: str | None = None) -> None:
        self.token = token

    def with_credentials(self, secrets, *, metadata):
        token = secrets.get("api_key")
        if not token:
            raise ValueError("api_key is required")
        return CredentialAwareTestConnector(token=token)

    def discover(self, query, *, cursor=None, limit=10):
        if not self.token:
            raise ValueError("credentials are required")
        return DiscoveryPage(
            resources=(
                DiscoveredResource(
                    canonical_uri="https://example.com/private",
                    provider=self.name,
                    title=f"authenticated:{query}",
                    metadata={"authenticated": True},
                ),
            )
        )

    def health(self):
        return ConnectorHealth(
            name=self.name,
            state=ConnectorState.READY,
            capabilities=("discover", "credentials"),
        )


def test_encrypted_connector_credential_lifecycle_and_discovery() -> None:
    database_url = _database_url()
    os.environ["ARVECTUM_DATA_DATABASE_URL"] = database_url
    command.upgrade(Config("alembic.ini"), "head")

    registry = ConnectorRegistry()
    registry.register(CredentialAwareTestConnector())
    settings = Settings(
        environment="test",
        log_level="WARNING",
        database_url=database_url,
        internal_api_key="admin-secret",
        embedding_provider="hashing",
        embedding_model="credential-test-hash",
        embedding_dimension=16,
        connector_credentials_master_key="credential-master-key-" + "x" * 32,
    )
    platform = DataPlatformService(
        settings,
        connector_registry=registry,
        embedding_provider=HashingEmbeddingProvider(dimension=16),
    )
    app = create_app(settings, platform_service=platform)
    client = TestClient(app)
    admin = {"X-Arvectum-Key": "admin-secret"}
    consumer_id = f"credential-{uuid.uuid4().hex[:8]}"
    tenant_id = f"tenant-{uuid.uuid4().hex[:8]}"

    issued = client.post(
        "/v1/auth/consumer-keys",
        headers=admin,
        json={
            "consumer_id": consumer_id,
            "tenant_id": tenant_id,
            "label": "credential integration",
        },
    )
    assert issued.status_code == 200
    consumer_headers = {
        "X-Arvectum-Consumer": consumer_id,
        "X-Arvectum-Consumer-Key": issued.json()["secret"],
    }

    plaintext = "first-super-secret"
    created = client.post(
        "/v1/connectors/credentials",
        headers=consumer_headers,
        json={
            "connector": "credential-test",
            "label": "test key",
            "secrets": {"api_key": plaintext},
            "metadata": {"account": "integration"},
        },
    )
    assert created.status_code == 200
    credential_id = created.json()["credential_id"]
    assert created.json()["tenant_id"] == tenant_id
    assert plaintext not in created.text

    with platform._require_factory()() as session:
        stored = session.scalar(
            select(ConnectorCredentialRow).where(
                ConnectorCredentialRow.credential_id == credential_id
            )
        )
        assert stored is not None
        assert plaintext not in stored.secret_ciphertext
        assert stored.metadata_json == {"account": "integration"}

    discovered = client.post(
        "/v1/discover",
        headers=consumer_headers,
        json={
            "connector": "credential-test",
            "query": "supplier",
            "credential_id": credential_id,
        },
    )
    assert discovered.status_code == 200
    assert discovered.json()["resources"][0]["title"] == "authenticated:supplier"

    rotated = client.post(
        f"/v1/connectors/credentials/{credential_id}/rotate",
        headers=consumer_headers,
        json={"secrets": {"api_key": "second-super-secret"}},
    )
    assert rotated.status_code == 200
    replacement_id = rotated.json()["credential_id"]
    assert replacement_id != credential_id

    old_denied = client.post(
        "/v1/discover",
        headers=consumer_headers,
        json={
            "connector": "credential-test",
            "query": "supplier",
            "credential_id": credential_id,
        },
    )
    assert old_denied.status_code == 403

    replacement_allowed = client.post(
        "/v1/discover",
        headers=consumer_headers,
        json={
            "connector": "credential-test",
            "query": "supplier",
            "credential_id": replacement_id,
        },
    )
    assert replacement_allowed.status_code == 200

    revoked = client.post(
        f"/v1/connectors/credentials/{replacement_id}/revoke",
        headers=consumer_headers,
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"

    revoked_denied = client.post(
        "/v1/discover",
        headers=consumer_headers,
        json={
            "connector": "credential-test",
            "query": "supplier",
            "credential_id": replacement_id,
        },
    )
    assert revoked_denied.status_code == 403
