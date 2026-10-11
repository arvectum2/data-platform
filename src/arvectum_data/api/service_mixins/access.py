from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker


from ...search import (
    SearchQuery,
)
from ...storage.postgres import (
    ChunkEmbeddingRow,
    ChunkRow,
    CollectionRow,
    ConsumerApiKeyRow,
    DocumentRow,
    PipelineRunRow,
    ResourceRow,
)


from ..access_payloads import (
    _consumer_key_payload,
    _connector_credential_payload,
    _normalize_credential_metadata,
)

from ..service_support import (
    PlatformNotConfigured,
    CollectionAccessDenied,
    TenantQuotaExceeded,
)


class AccessServiceMixin:
    # Historical static facades retained for downstream imports.
    _consumer_key_payload = staticmethod(_consumer_key_payload)
    _connector_credential_payload = staticmethod(_connector_credential_payload)
    _normalize_credential_metadata = staticmethod(_normalize_credential_metadata)


    @staticmethod
    def _active_tenants_for_consumer(
        session: Session,
        consumer_id: str,
    ) -> set[str]:
        # DISTINCT/LIMIT 2 is enough to detect ambiguous tenants without
        # loading arbitrarily many API keys or their sensitive credentials.
        now = datetime.now(UTC)
        return set(session.scalars(
            select(ConsumerApiKeyRow.tenant_id).where(
                ConsumerApiKeyRow.consumer_id == consumer_id,
                ConsumerApiKeyRow.status == "active",
                ConsumerApiKeyRow.tenant_id.is_not(None),
                ConsumerApiKeyRow.tenant_id != "",
                or_(
                    ConsumerApiKeyRow.expires_at.is_(None),
                    ConsumerApiKeyRow.expires_at > now,
                ),
            ).distinct().limit(2)
        ))


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
            tenants = self._active_tenants_for_consumer(active_session, consumer)
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
