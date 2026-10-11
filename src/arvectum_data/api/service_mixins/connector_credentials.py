from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from ...connectors import (
    CredentialCipher,
)

from ...storage.postgres import (
    ConnectorCredentialRow,
)

from ..access_payloads import (
    _connector_credential_payload,
    _normalize_credential_metadata,
)

from ..service_support import (
    PlatformNotConfigured,
    CollectionAccessDenied,
    ConnectorCredentialNotFound,
)


class ConnectorCredentialServiceMixin:
    def _credential_cipher(self) -> CredentialCipher:
        master_key = self.settings.connector_credentials_master_key.strip()
        if not master_key:
            raise PlatformNotConfigured("connector credential vault is not configured")
        return CredentialCipher(
            master_key,
            key_version=self.settings.connector_credentials_key_version,
        )

    _connector_credential_payload = staticmethod(_connector_credential_payload)

    _normalize_credential_metadata = staticmethod(_normalize_credential_metadata)

    def create_connector_credential(
        self,
        *,
        consumer_id: str,
        connector_name: str,
        secrets: Mapping[str, str],
        label: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        consumer_id = consumer_id.strip()
        connector_name = connector_name.strip()
        if not consumer_id:
            raise ValueError("consumer_id must not be blank")
        if not connector_name or len(connector_name) > 128:
            raise ValueError("connector must be between 1 and 128 characters")
        if label is not None and len(label.strip()) > 128:
            raise ValueError("connector credential label is too long")
        self.connector_registry.get(connector_name)
        cipher = self._credential_cipher()
        ciphertext = cipher.encrypt(secrets)
        safe_metadata = self._normalize_credential_metadata(metadata)
        with self._require_factory()() as session:
            tenant_id = self._consumer_tenant(consumer_id, session=session)
            if not tenant_id:
                raise CollectionAccessDenied(
                    "connector credentials require a tenant-bound consumer"
                )
            row = ConnectorCredentialRow(
                tenant_id=tenant_id,
                consumer_id=consumer_id,
                connector_name=connector_name,
                label=label.strip() if label else None,
                key_version=cipher.key_version,
                secret_ciphertext=ciphertext,
                metadata_json=safe_metadata,
                status="active",
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._connector_credential_payload(row)

    def list_connector_credentials(
        self,
        *,
        consumer_id: str,
        connector_name: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._require_factory()() as session:
            tenant_id = self._consumer_tenant(consumer_id, session=session)
            if not tenant_id:
                return []
            statement = select(ConnectorCredentialRow).where(
                ConnectorCredentialRow.consumer_id == consumer_id,
                ConnectorCredentialRow.tenant_id == tenant_id,
            )
            if connector_name:
                statement = statement.where(
                    ConnectorCredentialRow.connector_name == connector_name.strip()
                )
            statement = statement.order_by(
                ConnectorCredentialRow.created_at.desc(),
                ConnectorCredentialRow.credential_id.desc(),
            )
            return [self._connector_credential_payload(row) for row in session.scalars(statement)]

    def resolve_connector_credential(
        self,
        credential_id: str,
        *,
        consumer_id: str,
        connector_name: str,
    ) -> dict[str, Any]:
        cipher = self._credential_cipher()
        with self._require_factory()() as session:
            row = session.get(ConnectorCredentialRow, credential_id)
            if row is None:
                raise ConnectorCredentialNotFound(credential_id)
            tenant_id = self._consumer_tenant(consumer_id, session=session)
            if (
                row.status != "active"
                or row.consumer_id != consumer_id
                or row.tenant_id != tenant_id
                or row.connector_name != connector_name
            ):
                raise CollectionAccessDenied("connector credential access denied")
            secrets = cipher.decrypt(
                row.secret_ciphertext,
                key_version=row.key_version,
            )
            return {
                **self._connector_credential_payload(row),
                "secrets": secrets,
            }

    def revoke_connector_credential(
        self,
        credential_id: str,
        *,
        consumer_id: str,
    ) -> dict[str, Any]:
        with self._require_factory()() as session:
            row = session.get(ConnectorCredentialRow, credential_id)
            if row is None:
                raise LookupError("connector credential not found")
            tenant_id = self._consumer_tenant(consumer_id, session=session)
            if row.consumer_id != consumer_id or row.tenant_id != tenant_id:
                raise CollectionAccessDenied("connector credential access denied")
            if row.status != "revoked":
                row.status = "revoked"
                row.revoked_at = datetime.now(UTC)
                session.add(row)
                session.commit()
                session.refresh(row)
            return self._connector_credential_payload(row)

    def rotate_connector_credential(
        self,
        credential_id: str,
        *,
        consumer_id: str,
        secrets: Mapping[str, str],
        label: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        cipher = self._credential_cipher()
        ciphertext = cipher.encrypt(secrets)
        with self._require_factory()() as session:
            row = session.get(ConnectorCredentialRow, credential_id)
            if row is None:
                raise LookupError("connector credential not found")
            tenant_id = self._consumer_tenant(consumer_id, session=session)
            if (
                row.status != "active"
                or row.consumer_id != consumer_id
                or row.tenant_id != tenant_id
            ):
                raise CollectionAccessDenied("connector credential access denied")
            row.status = "revoked"
            row.revoked_at = datetime.now(UTC)
            replacement = ConnectorCredentialRow(
                tenant_id=row.tenant_id,
                consumer_id=row.consumer_id,
                connector_name=row.connector_name,
                label=(label.strip() if label else row.label),
                key_version=cipher.key_version,
                secret_ciphertext=ciphertext,
                metadata_json=(
                    self._normalize_credential_metadata(metadata)
                    if metadata is not None
                    else dict(row.metadata_json or {})
                ),
                status="active",
            )
            session.add(row)
            session.add(replacement)
            session.commit()
            session.refresh(replacement)
            return self._connector_credential_payload(replacement)
