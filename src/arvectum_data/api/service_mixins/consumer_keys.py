from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session


from ...storage.postgres import (
    ConsumerApiKeyRow,
)

from ..access_payloads import (
    _consumer_key_payload,
)

from ..service_support import (
    ConsumerKeyNotFound,
)


class ConsumerKeyServiceMixin:
    @staticmethod
    def _lock_consumer_key_issuance(session: Session, consumer_id: str) -> None:
        """Serialize concurrent API-key issuance for the same consumer in PostgreSQL."""
        session.execute(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtextextended(f"arvectum:consumer:key:{consumer_id}", 0)
                )
            )
        )

    _consumer_key_payload = staticmethod(_consumer_key_payload)

    def create_consumer_key(
        self,
        *,
        consumer_id: str,
        tenant_id: str | None = None,
        label: str | None = None,
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        consumer_id = consumer_id.strip()
        if not consumer_id:
            raise ValueError("consumer_id must not be blank")
        tenant_id = tenant_id.strip() if tenant_id else None
        if expires_at is not None:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= datetime.now(UTC):
                raise ValueError("expires_at must be in the future")
        with self._require_factory()() as session:
            self._lock_consumer_key_issuance(session, consumer_id)
            existing_tenants = self._active_tenants_for_consumer(session, consumer_id)
            if len(existing_tenants) > 1:
                raise ValueError("consumer is associated with multiple active tenants")
            if existing_tenants and tenant_id not in existing_tenants:
                raise ValueError("consumer already belongs to another active tenant")

            secret = "avk_" + secrets.token_urlsafe(32)
            digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
            row = ConsumerApiKeyRow(
                consumer_id=consumer_id,
                tenant_id=tenant_id,
                key_hash=digest,
                key_prefix=secret[:12],
                label=label.strip() if label else None,
                status="active",
                expires_at=expires_at,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return {**self._consumer_key_payload(row), "secret": secret}

    def list_consumer_keys(
        self,
        *,
        consumer_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._require_factory()() as session:
            query = select(ConsumerApiKeyRow).order_by(
                ConsumerApiKeyRow.created_at.desc(),
                ConsumerApiKeyRow.key_id.desc(),
            )
            if consumer_id:
                query = query.where(ConsumerApiKeyRow.consumer_id == consumer_id)
            return [self._consumer_key_payload(row) for row in session.scalars(query)]

    def authenticate_consumer_key(self, consumer_id: str, secret: str) -> bool:
        if not consumer_id or not secret or self.session_factory is None:
            return False
        digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        now = datetime.now(UTC)
        with self._require_factory()() as session:
            row = session.scalar(
                select(ConsumerApiKeyRow).where(
                    ConsumerApiKeyRow.consumer_id == consumer_id,
                    ConsumerApiKeyRow.key_hash == digest,
                    ConsumerApiKeyRow.status == "active",
                    or_(
                        ConsumerApiKeyRow.expires_at.is_(None),
                        ConsumerApiKeyRow.expires_at > now,
                    ),
                )
            )
            return row is not None

    def revoke_consumer_key(self, key_id: str) -> dict[str, Any]:
        with self._require_factory()() as session:
            row = session.get(ConsumerApiKeyRow, key_id)
            if row is None:
                raise ConsumerKeyNotFound(key_id)
            if row.status != "revoked":
                row.status = "revoked"
                row.revoked_at = datetime.now(UTC)
                session.add(row)
                session.commit()
                session.refresh(row)
            return self._consumer_key_payload(row)

    def rotate_consumer_key(self, key_id: str) -> dict[str, Any]:
        with self._require_factory()() as session:
            row = session.get(ConsumerApiKeyRow, key_id)
            if row is None:
                raise ConsumerKeyNotFound(key_id)
            if row.status != "active":
                raise ValueError("only active consumer keys can be rotated")
            if row.expires_at is not None and row.expires_at <= datetime.now(UTC):
                raise ValueError("expired consumer key cannot be rotated")
            consumer_id = row.consumer_id
            tenant_id = row.tenant_id
            label = row.label
            expires_at = row.expires_at
            row.status = "revoked"
            row.revoked_at = datetime.now(UTC)
            secret = "avk_" + secrets.token_urlsafe(32)
            replacement = ConsumerApiKeyRow(
                consumer_id=consumer_id,
                tenant_id=tenant_id,
                key_hash=hashlib.sha256(secret.encode("utf-8")).hexdigest(),
                key_prefix=secret[:12],
                label=label,
                status="active",
                expires_at=expires_at,
            )
            session.add(row)
            session.add(replacement)
            session.commit()
            session.refresh(replacement)
            return {**self._consumer_key_payload(replacement), "secret": secret}
