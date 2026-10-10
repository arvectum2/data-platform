from __future__ import annotations

import hashlib
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker

from ...connectors import (
    ConnectorRegistry,
    CredentialCipher,
    DiscoveredResource,
    DuckDuckGoHTMLConnector,
    GitHubRepositoryConnector,
    ManualURLConnector,
    SitemapConnector,
)
from ...models import ModelLocality, ModelPolicy, ModelRole, ModelRouter, RoleConfig

from ...search import (
    SearchQuery,
)
from ...storage.postgres import (
    ChunkEmbeddingRow,
    ChunkRow,
    CollectionRow,
    ConnectorCredentialRow,
    ConsumerApiKeyRow,
    DocumentRow,
    PipelineRunRow,
    ResourceRow,
)
from ..config import Settings

from ..service_support import (
    PlatformNotConfigured,
    CollectionNotFound,
    CollectionAccessDenied,
    TenantQuotaExceeded,
    ConsumerKeyNotFound,
    ConnectorCredentialNotFound,
)


class AccessServiceMixin:
    def _credential_cipher(self) -> CredentialCipher:
        master_key = self.settings.connector_credentials_master_key.strip()
        if not master_key:
            raise PlatformNotConfigured("connector credential vault is not configured")
        return CredentialCipher(
            master_key,
            key_version=self.settings.connector_credentials_key_version,
        )

    def _consumer_tenant(
        self,
        consumer: str | None,
        *,
        session: Session | None = None,
    ) -> str:
        if consumer is None:
            return ""
        configured = self.settings.consumer_tenants.get(consumer, "")
        if configured:
            return configured
        if self.session_factory is None:
            return ""

        def resolve(active_session: Session) -> str:
            now = datetime.now(UTC)
            tenants = {
                str(value)
                for value in active_session.scalars(
                    select(ConsumerApiKeyRow.tenant_id).where(
                        ConsumerApiKeyRow.consumer_id == consumer,
                        ConsumerApiKeyRow.status == "active",
                        or_(
                            ConsumerApiKeyRow.expires_at.is_(None),
                            ConsumerApiKeyRow.expires_at > now,
                        ),
                    )
                )
                if value
            }
            if len(tenants) > 1:
                raise ValueError("consumer is associated with multiple active tenants")
            return next(iter(tenants), "")

        if session is not None:
            return resolve(session)
        with self._require_factory()() as active_session:
            return resolve(active_session)

    def _authorize_collection_consumer(
        self,
        collection: CollectionRow,
        consumer: str | None,
        *,
        session: Session | None = None,
        resolved_tenant: str | None = None,
    ) -> None:
        policy = dict(collection.access_policy or {})
        tenant_id = str(policy.get("tenant_id") or "").strip()
        if tenant_id:
            effective_tenant = (
                resolved_tenant
                if resolved_tenant is not None
                else self._consumer_tenant(consumer, session=session)
            )
            if effective_tenant != tenant_id:
                raise CollectionAccessDenied(collection.collection_id)
        allowed_consumers = tuple(
            str(item) for item in policy.get("allowed_consumers", []) if str(item)
        )
        if allowed_consumers and consumer not in allowed_consumers:
            raise CollectionAccessDenied(collection.collection_id)

    def _validate_tenant_search_quota(
        self,
        request: SearchQuery,
        consumer: str | None,
    ) -> str:
        # Return the resolved identity to reuse for all collection checks in
        # the same request. Do not cache it across requests or key rotations.
        if consumer is None:
            return ""
        tenant_id = self._consumer_tenant(consumer)
        if not tenant_id:
            return ""
        quota = dict(self.settings.tenant_quotas.get(tenant_id) or {})
        checks = {
            "max_collections_per_search": len(request.collections),
            "max_results_per_search": request.limit,
            "max_rerank_candidates": (request.rerank_candidates if request.rerank else 0),
            "max_query_variants": len(request.query_variants),
        }
        for key, actual in checks.items():
            raw_limit = quota.get(key)
            if raw_limit is None:
                continue
            limit = int(raw_limit)
            if limit < 0:
                raise ValueError(f"tenant quota {key} must be non-negative")
            if actual > limit:
                raise TenantQuotaExceeded(
                    f"tenant {tenant_id!r} quota exceeded: {key}={actual} > {limit}"
                )
        return tenant_id

    @staticmethod
    def _default_connector_registry() -> ConnectorRegistry:
        registry = ConnectorRegistry()
        registry.register(ManualURLConnector())
        registry.register(SitemapConnector())
        registry.register(DuckDuckGoHTMLConnector())
        registry.register(GitHubRepositoryConnector())
        return registry

    @staticmethod
    def _build_model_router(settings: Settings) -> ModelRouter:
        common = {
            "timeout_seconds": settings.model_timeout_seconds,
            "retry_max_attempts": settings.model_retry_max_attempts,
            "retry_base_delay_seconds": settings.model_retry_base_delay_seconds,
            "max_concurrency": settings.model_max_concurrency,
        }

        def role_config(prefix: str) -> RoleConfig:
            allowlist = tuple(
                item.strip()
                for item in getattr(settings, f"{prefix}_remote_allowlist").split(",")
                if item.strip()
            )
            version = getattr(settings, f"{prefix}_model_version").strip() or None
            return RoleConfig(
                policy=ModelPolicy(getattr(settings, f"{prefix}_policy")),
                provider=getattr(settings, f"{prefix}_provider"),
                model=getattr(settings, f"{prefix}_model"),
                version=version,
                base_url=getattr(settings, f"{prefix}_base_url"),
                locality=ModelLocality(getattr(settings, f"{prefix}_locality")),
                remote_allowlist=allowlist,
                api_key=getattr(settings, f"{prefix}_api_key"),
                **common,
            )

        return ModelRouter.build(
            reasoning=role_config("reasoning"),
            vision=role_config("vision"),
        )

    def model_status(self, *, probe: bool = False) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for role, readiness in self.model_router.readiness(probe=probe).items():
            descriptor = readiness.descriptor
            provider = self.model_router.provider(ModelRole(role))
            metrics = getattr(provider, "metrics", None)
            result[role] = {
                "enabled": readiness.enabled,
                "ready": readiness.ready,
                "provider": descriptor.provider if descriptor else None,
                "model": descriptor.model if descriptor else None,
                "version": descriptor.version if descriptor else None,
                "locality": descriptor.locality.value if descriptor else None,
                "capabilities": list(descriptor.capabilities) if descriptor else [],
                "latency_ms": readiness.latency_ms,
                "error_type": readiness.error_type,
                "metrics": (metrics.snapshot().__dict__ if metrics is not None else None),
            }
        return result

    def connector_status(self) -> list[dict[str, Any]]:
        return [
            {
                "name": item.name,
                "state": item.state.value,
                "capabilities": list(item.capabilities),
                "detail": item.detail,
                "metadata": dict(item.metadata),
            }
            for item in self.connector_registry.health()
        ]

    def _connector_for_request(
        self,
        connector_name: str,
        *,
        consumer: str | None = None,
        credential_id: str | None = None,
    ):
        connector = self.connector_registry.get(connector_name)
        if credential_id is None:
            return connector
        if consumer is None:
            raise CollectionAccessDenied("connector credential requires consumer identity")
        credential = self.resolve_connector_credential(
            credential_id,
            consumer_id=consumer,
            connector_name=connector_name,
        )
        configure = getattr(connector, "with_credentials", None)
        if configure is None:
            raise ValueError(f"connector {connector_name!r} does not support managed credentials")
        return configure(
            credential["secrets"],
            metadata=credential["metadata"],
        )

    def discover(
        self,
        *,
        connector_name: str,
        query: str,
        cursor: str | None = None,
        limit: int = 10,
        consumer: str | None = None,
        credential_id: str | None = None,
    ):
        connector = self._connector_for_request(
            connector_name,
            consumer=consumer,
            credential_id=credential_id,
        )
        discover = getattr(connector, "discover", None)
        if discover is None:
            raise ValueError(f"connector {connector_name!r} does not support discovery")
        return discover(query, cursor=cursor, limit=limit)

    def ingest_discovered_resource(
        self,
        *,
        collection_id: str,
        connector_name: str,
        resource: DiscoveredResource,
        consumer: str | None = None,
        credential_id: str | None = None,
    ) -> dict[str, Any]:
        with self._require_factory()() as session:
            collection = session.get(CollectionRow, collection_id)
            if collection is None:
                raise CollectionNotFound(collection_id)
            self._authorize_collection_consumer(
                collection,
                consumer,
                session=session,
            )

        connector = self._connector_for_request(
            connector_name,
            consumer=consumer,
            credential_id=credential_id,
        )
        fetch = getattr(connector, "fetch", None)
        if fetch is None:
            raise ValueError(f"connector {connector_name!r} does not support fetch")
        acquired = fetch(resource)
        asset = acquired.asset
        if asset.html is not None:
            content = asset.html.encode("utf-8")
            filename = str(resource.metadata.get("path") or resource.title or "resource.html")
            if not Path(filename).suffix:
                filename += ".html"
        else:
            content = (asset.text or "").encode("utf-8")
            filename = str(resource.metadata.get("path") or resource.title or "resource.txt")
            if not Path(filename).suffix:
                filename += ".txt"
        return self.ingest_document_bytes(
            collection_id=collection_id,
            filename=filename,
            content=content,
            title=resource.title,
            canonical_uri=resource.canonical_uri,
        )

    def _require_factory(self) -> sessionmaker[Session]:
        if self.session_factory is None:
            raise PlatformNotConfigured("ARVECTUM_DATA_DATABASE_URL is not configured")
        return self.session_factory

    def status(self) -> dict[str, Any]:
        database_ok = False
        metrics: dict[str, int] = {}
        if self.session_factory is not None:
            try:
                with self.session_factory() as session:
                    session.execute(text("SELECT 1"))
                    metrics = {
                        "collections": int(
                            session.scalar(select(func.count()).select_from(CollectionRow)) or 0
                        ),
                        "resources": int(
                            session.scalar(select(func.count()).select_from(ResourceRow)) or 0
                        ),
                        "documents": int(
                            session.scalar(select(func.count()).select_from(DocumentRow)) or 0
                        ),
                        "chunks": int(
                            session.scalar(select(func.count()).select_from(ChunkRow)) or 0
                        ),
                        "embeddings": int(
                            session.scalar(select(func.count()).select_from(ChunkEmbeddingRow)) or 0
                        ),
                        "index_jobs": int(
                            session.scalar(select(func.count()).select_from(PipelineRunRow)) or 0
                        ),
                    }
                database_ok = True
            except Exception:
                database_ok = False
                metrics = {}
        return {
            "status": ("ok" if self.session_factory is None or database_ok else "degraded"),
            "deployment_mode": self.settings.deployment_mode,
            "database_configured": self.session_factory is not None,
            "embedding_provider": self.embedding_provider.provider_name,
            "embedding_model": self.embedding_provider.model_name,
            "embedding_dimension": self.embedding_provider.dimension,
            "ocr_provider": (
                self.ocr_provider.provider_name if self.ocr_provider is not None else None
            ),
            "model_roles": self.model_status(probe=False),
            "metrics": metrics,
        }

    @staticmethod
    def _consumer_key_payload(row: ConsumerApiKeyRow) -> dict[str, Any]:
        return {
            "key_id": row.key_id,
            "consumer_id": row.consumer_id,
            "tenant_id": row.tenant_id,
            "key_prefix": row.key_prefix,
            "label": row.label,
            "status": row.status,
            "created_at": row.created_at,
            "expires_at": row.expires_at,
            "revoked_at": row.revoked_at,
        }

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
            existing_tenants = {
                str(value)
                for value in session.scalars(
                    select(ConsumerApiKeyRow.tenant_id).where(
                        ConsumerApiKeyRow.consumer_id == consumer_id,
                        ConsumerApiKeyRow.status == "active",
                        or_(
                            ConsumerApiKeyRow.expires_at.is_(None),
                            ConsumerApiKeyRow.expires_at > datetime.now(UTC),
                        ),
                    )
                )
                if value
            }
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

    @staticmethod
    def _connector_credential_payload(row: ConnectorCredentialRow) -> dict[str, Any]:
        return {
            "credential_id": row.credential_id,
            "tenant_id": row.tenant_id,
            "consumer_id": row.consumer_id,
            "connector": row.connector_name,
            "label": row.label,
            "status": row.status,
            "metadata": dict(row.metadata_json or {}),
            "created_at": row.created_at,
            "revoked_at": row.revoked_at,
        }

    @staticmethod
    def _normalize_credential_metadata(
        metadata: Mapping[str, object] | None,
    ) -> dict[str, object]:
        result = dict(metadata or {})
        if len(result) > 32:
            raise ValueError("connector credential metadata may contain at most 32 keys")
        blocked_fragments = (
            "secret",
            "password",
            "token",
            "api_key",
            "apikey",
            "authorization",
        )
        for key, value in result.items():
            normalized_key = str(key).strip()
            if not normalized_key or len(normalized_key) > 128:
                raise ValueError("connector credential metadata keys must be 1..128 characters")
            lowered_key = normalized_key.casefold()
            if any(fragment in lowered_key for fragment in blocked_fragments):
                raise ValueError("sensitive connector credential values must be stored in secrets")
            if isinstance(value, (dict, list, tuple, set)):
                raise ValueError("connector credential metadata must contain scalar values only")
            if value is not None and len(str(value)) > 1024:
                raise ValueError("connector credential metadata values are too large")
        return result

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
