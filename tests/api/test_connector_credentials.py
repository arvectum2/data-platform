from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from arvectum_data.api.app import create_app
from arvectum_data.api.config import Settings
from arvectum_data.connectors import DiscoveryPage, DiscoveredResource


class FakeCredentialService:
    def __init__(self) -> None:
        self.credentials: dict[str, dict] = {}
        self.last_discover: dict | None = None

    def status(self):
        return {
            "status": "ok",
            "database_configured": True,
            "embedding_provider": "hashing",
            "embedding_model": "local-hash-v1",
            "embedding_dimension": 16,
            "metrics": {},
        }

    def create_connector_credential(
        self,
        *,
        consumer_id,
        connector_name,
        secrets,
        label=None,
        metadata=None,
    ):
        credential_id = "credential-1"
        row = {
            "credential_id": credential_id,
            "tenant_id": "tenant-1",
            "consumer_id": consumer_id,
            "connector": connector_name,
            "label": label,
            "status": "active",
            "metadata": dict(metadata or {}),
            "created_at": datetime(2026, 10, 6, tzinfo=UTC),
            "revoked_at": None,
        }
        self.credentials[credential_id] = row
        return row

    def list_connector_credentials(self, *, consumer_id, connector_name=None):
        rows = [
            row
            for row in self.credentials.values()
            if row["consumer_id"] == consumer_id
            and (connector_name is None or row["connector"] == connector_name)
        ]
        return rows

    def rotate_connector_credential(
        self,
        credential_id,
        *,
        consumer_id,
        secrets,
        label=None,
        metadata=None,
    ):
        old = self.credentials[credential_id]
        old["status"] = "revoked"
        old["revoked_at"] = datetime(2026, 10, 6, tzinfo=UTC)
        new_id = "credential-2"
        row = {
            **old,
            "credential_id": new_id,
            "label": label or old["label"],
            "status": "active",
            "metadata": dict(metadata if metadata is not None else old["metadata"]),
            "created_at": datetime(2026, 10, 6, tzinfo=UTC),
            "revoked_at": None,
        }
        self.credentials[new_id] = row
        return row

    def revoke_connector_credential(self, credential_id, *, consumer_id):
        row = self.credentials[credential_id]
        row["status"] = "revoked"
        row["revoked_at"] = datetime(2026, 10, 6, tzinfo=UTC)
        return row

    def connector_status(self):
        return []

    def discover(
        self,
        *,
        connector_name,
        query,
        cursor=None,
        limit=10,
        consumer=None,
        credential_id=None,
    ):
        self.last_discover = {
            "connector": connector_name,
            "consumer": consumer,
            "credential_id": credential_id,
        }
        return DiscoveryPage(
            resources=(
                DiscoveredResource(
                    canonical_uri="https://example.com/private-result",
                    provider=connector_name,
                    title=query,
                    rank=1,
                ),
            )
        )


def _client(service: FakeCredentialService) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                environment="test",
                log_level="WARNING",
                internal_api_key="admin-secret",
                consumer_api_keys={"external": "consumer-secret"},
            ),
            platform_service=service,
        )
    )


def _headers() -> dict[str, str]:
    return {
        "X-Arvectum-Consumer": "external",
        "X-Arvectum-Consumer-Key": "consumer-secret",
    }


def test_credential_lifecycle_never_returns_secret_payload() -> None:
    service = FakeCredentialService()
    client = _client(service)

    created = client.post(
        "/v1/connectors/credentials",
        headers=_headers(),
        json={
            "connector": "private-search",
            "label": "customer key",
            "secrets": {"api_key": "do-not-return-me"},
            "metadata": {"account": "customer-a"},
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["credential_id"] == "credential-1"
    assert body["tenant_id"] == "tenant-1"
    assert "secrets" not in body
    assert "do-not-return-me" not in created.text

    listed = client.get("/v1/connectors/credentials", headers=_headers())
    assert listed.status_code == 200
    assert listed.json()[0]["credential_id"] == "credential-1"
    assert "secrets" not in listed.json()[0]

    rotated = client.post(
        "/v1/connectors/credentials/credential-1/rotate",
        headers=_headers(),
        json={"secrets": {"api_key": "new-secret"}},
    )
    assert rotated.status_code == 200
    assert rotated.json()["credential_id"] == "credential-2"
    assert "new-secret" not in rotated.text

    revoked = client.post(
        "/v1/connectors/credentials/credential-2/revoke",
        headers=_headers(),
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"


def test_credential_management_requires_consumer_identity() -> None:
    client = _client(FakeCredentialService())

    response = client.post(
        "/v1/connectors/credentials",
        headers={"X-Arvectum-Key": "admin-secret"},
        json={
            "connector": "private-search",
            "secrets": {"api_key": "secret"},
        },
    )

    assert response.status_code == 403


def test_discovery_forwards_authenticated_credential_reference() -> None:
    service = FakeCredentialService()
    client = _client(service)

    response = client.post(
        "/v1/discover",
        headers=_headers(),
        json={
            "connector": "private-search",
            "query": "supplier",
            "credential_id": "credential-1",
        },
    )

    assert response.status_code == 200
    assert response.json()["resources"][0]["canonical_uri"] == (
        "https://example.com/private-result"
    )
    assert service.last_discover == {
        "connector": "private-search",
        "consumer": "external",
        "credential_id": "credential-1",
    }
