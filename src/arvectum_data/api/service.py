from __future__ import annotations

import hashlib
import os
import secrets
import tempfile
import threading
import time
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import case, func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker

from ..acquisition import AcquisitionEngine
from ..answers import GroundedAnswer, ReasoningAnswerSynthesizer
from ..acquisition.security import UnsafeURL, validate_public_url
from ..documents import TesseractOCRProvider, ingest_file, ingest_url
from ..graph import EvidenceGraphSuggester, GraphSuggestions
from ..processing import ChunkingConfig
from ..research import ResearchResult, ResearchWorkflow
from ..connectors import (
    ConnectorRegistry,
    CredentialCipher,
    DuckDuckGoHTMLConnector,
    GitHubRepositoryConnector,
    ManualURLConnector,
    SitemapConnector,
)
from ..engine import AutoDiscoveryProvider, ExtractionEngine, FieldSpec, RawAsset, ReasoningCandidateProvider
from ..entities import normalize_entity_value
from ..orchestration import URLExtractionPipeline
from ..indexing import (
    BaseEmbeddingProvider,
    EmbeddingConfig,
    EmbeddingServerUnavailableError,
    build_embedding_provider,
)
from ..modes import mode_profile
from ..models import ModelLocality, ModelPolicy, ModelRole, ModelRouter, RoleConfig
from ..memory import MemoryConflictPolicy, MemoryKind, MemoryWrite, build_memory_ingest
from ..sync import RefreshPolicy, RefreshResult

from ..search import (
    CrossEncoderReranker,
    HttpCrossEncoderScorer,
    HybridSearchEngine,
    PostgresSearchBackend,
    QueryExpansion,
    ReasoningQueryExpander,
    ReasoningReranker,
    RerankStrategy,
    SearchHit,
    SearchQuery,
    SearchStageDiagnostic,
    SentenceTransformersCrossEncoderScorer,
)
from ..storage.postgres import (
    ChunkEmbeddingRow,
    ChunkRow,
    CollectionRow,
    ConnectorCredentialRow,
    ConsumerApiKeyRow,
    DataRepository,
    DataRecordRow,
    DocumentRow,
    EntityAliasRow,
    EntityRow,
    EntityRelationRow,
    PipelineRunRow,
    ProvenanceRow,
    ResourceRow,
    RelevanceFeedbackRow,
    RefreshRunRow,
    UsageEventRow,
    build_engine,
    build_session_factory,
)
from .config import Settings




UnsafeUrlError = UnsafeURL


def validate_public_http_url(url: str) -> str:
    validate_public_url(url)
    return url


class PlatformNotConfigured(RuntimeError):
    pass


class CollectionNotFound(LookupError):
    pass


class CollectionAccessDenied(PermissionError):
    pass


class TenantQuotaExceeded(RuntimeError):
    pass


class ConsumerKeyNotFound(LookupError):
    pass


class ConnectorCredentialNotFound(LookupError):
    pass


class MemoryNotFound(LookupError):
    pass


class EntityNotFound(LookupError):
    pass


class EmbeddingContractMismatch(RuntimeError):
    pass



class IndexJobNotFound(LookupError):
    pass


def _collection_payload(row: CollectionRow) -> dict[str, Any]:
    return {
        "collection_id": row.collection_id,
        "owner": row.owner,
        "name": row.name,
        "default_language": row.default_language,
        "embedding_provider": row.embedding_provider,
        "embedding_model": row.embedding_model,
        "embedding_dimension": row.embedding_dimension,
        "active_index_revision": row.active_index_revision,
        "access_policy": dict(row.access_policy or {}),
        "retention_policy": dict(row.retention_policy or {}),
    }


class DataPlatformService:
    def __init__(
        self,
        settings: Settings,
        *,
        session_factory: sessionmaker[Session] | None = None,
        embedding_provider: BaseEmbeddingProvider | None = None,
        acquisition: AcquisitionEngine | None = None,
        connector_registry: ConnectorRegistry | None = None,
        model_router: ModelRouter | None = None,
    ) -> None:
        self.settings = settings
        self.acquisition = acquisition
        self.connector_registry = connector_registry or self._default_connector_registry()
        self.model_router = model_router or self._build_model_router(settings)
        self._cross_encoder_scorer = None
        self._cross_encoder_lock = threading.Lock()
        if settings.ocr_provider == "disabled":
            self.ocr_provider = None
        elif settings.ocr_provider == "tesseract":
            self.ocr_provider = TesseractOCRProvider(
                languages=settings.ocr_languages,
                dpi=settings.ocr_dpi,
                timeout_seconds=settings.ocr_timeout_seconds,
            )
        else:
            raise ValueError(f"unsupported OCR provider {settings.ocr_provider!r}")
        self.embedding_provider = embedding_provider or build_embedding_provider(
            EmbeddingConfig(
                provider=settings.embedding_provider,
                model=settings.embedding_model,
                base_url=settings.embedding_base_url,
                timeout_seconds=settings.embedding_timeout_seconds,
                dimension=settings.embedding_dimension,
            )
        )
        if session_factory is not None:
            self.session_factory = session_factory
        elif settings.database_url.strip():
            self.session_factory = build_session_factory(build_engine(settings.database_url))
        else:
            self.session_factory = None

    def _cross_encoder_reranker(
        self,
        *,
        max_candidates: int,
    ) -> CrossEncoderReranker | None:
        provider = self.settings.cross_encoder_provider.strip().lower()
        model_name = self.settings.cross_encoder_model.strip()
        if provider == "disabled" or not model_name:
            return None
        if self._cross_encoder_scorer is None:
            with self._cross_encoder_lock:
                if self._cross_encoder_scorer is None:
                    try:
                        if provider == "http":
                            self._cross_encoder_scorer = HttpCrossEncoderScorer(
                                base_url=self.settings.cross_encoder_base_url,
                                model_name=model_name,
                                timeout_seconds=self.settings.cross_encoder_timeout_seconds,
                            )
                        elif provider == "sentence_transformers":
                            self._cross_encoder_scorer = SentenceTransformersCrossEncoderScorer(
                                model_name
                            )
                        else:
                            return None
                    except Exception:
                        return None
        return CrossEncoderReranker(
            self._cross_encoder_scorer,
            max_candidates=min(
                max_candidates,
                self.settings.cross_encoder_max_candidates,
            ),
            max_candidate_chars=self.settings.cross_encoder_max_candidate_chars,
        )

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
    ) -> None:
        policy = dict(collection.access_policy or {})
        tenant_id = str(policy.get("tenant_id") or "").strip()
        if tenant_id:
            if self._consumer_tenant(consumer, session=session) != tenant_id:
                raise CollectionAccessDenied(collection.collection_id)
        allowed_consumers = tuple(
            str(item)
            for item in policy.get("allowed_consumers", [])
            if str(item)
        )
        if allowed_consumers and consumer not in allowed_consumers:
            raise CollectionAccessDenied(collection.collection_id)

    def _validate_tenant_search_quota(
        self,
        request: SearchQuery,
        consumer: str | None,
    ) -> None:
        if consumer is None:
            return
        tenant_id = self._consumer_tenant(consumer)
        if not tenant_id:
            return
        quota = dict(self.settings.tenant_quotas.get(tenant_id) or {})
        checks = {
            "max_collections_per_search": len(request.collections),
            "max_results_per_search": request.limit,
            "max_rerank_candidates": (
                request.rerank_candidates if request.rerank else 0
            ),
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
                    f"tenant {tenant_id!r} quota exceeded: "
                    f"{key}={actual} > {limit}"
                )

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
                "metrics": (
                    metrics.snapshot().__dict__
                    if metrics is not None
                    else None
                ),
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
        connector = self.connector_registry.get(connector_name)
        if credential_id is not None:
            if consumer is None:
                raise CollectionAccessDenied("connector credential requires consumer identity")
            credential = self.resolve_connector_credential(
                credential_id,
                consumer_id=consumer,
                connector_name=connector_name,
            )
            configure = getattr(connector, "with_credentials", None)
            if configure is None:
                raise ValueError(
                    f"connector {connector_name!r} does not support managed credentials"
                )
            connector = configure(
                credential["secrets"],
                metadata=credential["metadata"],
            )
        discover = getattr(connector, "discover", None)
        if discover is None:
            raise ValueError(f"connector {connector_name!r} does not support discovery")
        return discover(query, cursor=cursor, limit=limit)

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
            "status": (
                "ok"
                if self.session_factory is None or database_ok
                else "degraded"
            ),
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
            return [
                self._consumer_key_payload(row)
                for row in session.scalars(query)
            ]

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
                raise ValueError(
                    "sensitive connector credential values must be stored in secrets"
                )
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
            return [
                self._connector_credential_payload(row)
                for row in session.scalars(statement)
            ]

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

    @staticmethod
    def _usage_event_payload(row: UsageEventRow) -> dict[str, Any]:
        return {
            "usage_event_id": row.usage_event_id,
            "tenant_id": row.tenant_id,
            "consumer_id": row.consumer_id,
            "operation": row.operation,
            "unit": row.unit,
            "quantity": row.quantity,
            "billable": row.billable,
            "status_code": row.status_code,
            "request_id": row.request_id,
            "metadata": dict(row.metadata_json or {}),
            "created_at": row.created_at,
        }

    def record_usage_event(
        self,
        *,
        consumer_id: str,
        operation: str,
        request_id: str,
        status_code: int,
        unit: str = "request",
        quantity: int = 1,
        duration_ms: int | None = None,
        request_bytes: int | None = None,
    ) -> dict[str, Any]:
        consumer_id = consumer_id.strip()
        operation = operation.strip()
        unit = unit.strip()
        request_id = request_id.strip()
        if not consumer_id or len(consumer_id) > 128:
            raise ValueError("consumer_id must be between 1 and 128 characters")
        if not operation or len(operation) > 64:
            raise ValueError("operation must be between 1 and 64 characters")
        if not unit or len(unit) > 32:
            raise ValueError("unit must be between 1 and 32 characters")
        if not request_id or len(request_id) > 128:
            raise ValueError("request_id must be between 1 and 128 characters")
        if quantity < 0:
            raise ValueError("quantity must be non-negative")
        if status_code < 100 or status_code > 599:
            raise ValueError("status_code must be a valid HTTP status")
        if duration_ms is not None and duration_ms < 0:
            raise ValueError("duration_ms must be non-negative")
        if request_bytes is not None and request_bytes < 0:
            raise ValueError("request_bytes must be non-negative")

        usage_event_id = hashlib.sha256(
            "\x00".join((consumer_id, request_id, operation, unit)).encode("utf-8")
        ).hexdigest()
        with self._require_factory()() as session:
            existing = session.get(UsageEventRow, usage_event_id)
            if existing is not None:
                return self._usage_event_payload(existing)
            tenant_id = self._consumer_tenant(consumer_id, session=session) or None
            metadata: dict[str, int] = {}
            if duration_ms is not None:
                metadata["duration_ms"] = int(duration_ms)
            if request_bytes is not None:
                metadata["request_bytes"] = int(request_bytes)
            row = UsageEventRow(
                usage_event_id=usage_event_id,
                tenant_id=tenant_id,
                consumer_id=consumer_id,
                operation=operation,
                unit=unit,
                quantity=int(quantity),
                billable=200 <= status_code < 400,
                status_code=int(status_code),
                request_id=request_id,
                metadata_json=metadata,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._usage_event_payload(row)

    def usage_summary(
        self,
        *,
        tenant_id: str | None = None,
        consumer_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[str, Any]:
        if since is not None and since.tzinfo is None:
            since = since.replace(tzinfo=UTC)
        if until is not None and until.tzinfo is None:
            until = until.replace(tzinfo=UTC)
        if since is not None and until is not None and since >= until:
            raise ValueError("since must be earlier than until")
        tenant_id = tenant_id.strip() if tenant_id else None
        consumer_id = consumer_id.strip() if consumer_id else None

        with self._require_factory()() as session:
            statement = select(
                UsageEventRow.tenant_id,
                UsageEventRow.consumer_id,
                UsageEventRow.operation,
                UsageEventRow.unit,
                func.count(UsageEventRow.usage_event_id).label("events"),
                func.sum(UsageEventRow.quantity).label("quantity"),
                func.sum(
                    case(
                        (UsageEventRow.billable.is_(True), UsageEventRow.quantity),
                        else_=0,
                    )
                ).label("billable_quantity"),
            )
            if tenant_id is not None:
                statement = statement.where(UsageEventRow.tenant_id == tenant_id)
            if consumer_id is not None:
                statement = statement.where(UsageEventRow.consumer_id == consumer_id)
            if since is not None:
                statement = statement.where(UsageEventRow.created_at >= since)
            if until is not None:
                statement = statement.where(UsageEventRow.created_at < until)
            statement = statement.group_by(
                UsageEventRow.tenant_id,
                UsageEventRow.consumer_id,
                UsageEventRow.operation,
                UsageEventRow.unit,
            ).order_by(
                UsageEventRow.tenant_id,
                UsageEventRow.consumer_id,
                UsageEventRow.operation,
                UsageEventRow.unit,
            )
            buckets = [
                {
                    "tenant_id": row.tenant_id,
                    "consumer_id": row.consumer_id,
                    "operation": row.operation,
                    "unit": row.unit,
                    "events": int(row.events or 0),
                    "quantity": int(row.quantity or 0),
                    "billable_quantity": int(row.billable_quantity or 0),
                }
                for row in session.execute(statement)
            ]

        return {
            "since": since,
            "until": until,
            "total_events": sum(item["events"] for item in buckets),
            "total_quantity": sum(item["quantity"] for item in buckets),
            "billable_quantity": sum(item["billable_quantity"] for item in buckets),
            "buckets": buckets,
        }

    def create_collection(
        self,
        *,
        collection_id: str,
        owner: str,
        name: str,
        default_language: str,
        access_policy: Mapping[str, object] | None = None,
        retention_policy: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        with self._require_factory()() as session:
            repo = DataRepository(session)
            existing = session.get(CollectionRow, collection_id)
            if (
                existing is not None
                and not self._embedding_contract_matches(existing)
                and repo.collection_chunk_count(collection_id) > 0
            ):
                raise EmbeddingContractMismatch(
                    f"collection {collection_id!r} already contains indexed chunks with "
                    f"{self._collection_embedding_contract(existing)!r}; "
                    "run /v1/index/rebuild to migrate before changing the active embedding contract"
                )
            row = repo.ensure_collection(
                collection_id,
                owner=owner,
                name=name,
                default_language=default_language,
                embedding_provider=self.embedding_provider.provider_name,
                embedding_model=self.embedding_provider.model_name,
                embedding_dimension=self.embedding_provider.dimension,
                access_policy=None if access_policy is None else dict(access_policy),
                retention_policy=(
                    None if retention_policy is None else dict(retention_policy)
                ),
            )
            session.commit()
            return _collection_payload(row)

    def get_collection(self, collection_id: str) -> dict[str, Any]:
        with self._require_factory()() as session:
            row = session.get(CollectionRow, collection_id)
            if row is None:
                raise CollectionNotFound(collection_id)
            return _collection_payload(row)

    def list_collections(self) -> list[dict[str, Any]]:
        with self._require_factory()() as session:
            rows = session.scalars(
                select(CollectionRow).order_by(CollectionRow.collection_id.asc())
            ).all()
            return [_collection_payload(row) for row in rows]

    def export_collection(
        self,
        collection_id: str,
        *,
        include_content: bool = False,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._require_factory()() as session:
            collection = session.get(CollectionRow, collection_id)
            if collection is None:
                raise CollectionNotFound(collection_id)

            total_resources = int(
                session.scalar(
                    select(func.count())
                    .select_from(ResourceRow)
                    .where(ResourceRow.collection_id == collection_id)
                )
                or 0
            )
            resources = list(
                session.scalars(
                    select(ResourceRow)
                    .where(ResourceRow.collection_id == collection_id)
                    .order_by(ResourceRow.resource_id.asc())
                    .offset(offset)
                    .limit(limit)
                )
            )
            exported_resources: list[dict[str, Any]] = []
            for resource in resources:
                documents = list(
                    session.scalars(
                        select(DocumentRow)
                        .where(DocumentRow.resource_id == resource.resource_id)
                        .order_by(DocumentRow.document_id.asc())
                    )
                )
                exported_documents: list[dict[str, Any]] = []
                for document in documents:
                    chunks = list(
                        session.scalars(
                            select(ChunkRow)
                            .where(ChunkRow.document_id == document.document_id)
                            .order_by(ChunkRow.ordinal.asc())
                        )
                    )
                    exported_documents.append(
                        {
                            "document_id": document.document_id,
                            "title": document.title,
                            "text": document.text if include_content else None,
                            "media_type": document.media_type,
                            "content_hash": document.content_hash,
                            "extraction_status": document.extraction_status,
                            "metadata": dict(document.metadata_json or {}),
                            "chunks": [
                                {
                                    "chunk_id": chunk.chunk_id,
                                    "ordinal": chunk.ordinal,
                                    "text": chunk.text if include_content else None,
                                    "content_hash": chunk.content_hash,
                                    "char_start": chunk.char_start,
                                    "char_end": chunk.char_end,
                                    "token_estimate": chunk.token_estimate,
                                    "metadata": dict(chunk.metadata_json or {}),
                                }
                                for chunk in chunks
                            ],
                        }
                    )

                records = list(
                    session.scalars(
                        select(DataRecordRow)
                        .where(DataRecordRow.resource_id == resource.resource_id)
                        .order_by(DataRecordRow.record_id.asc())
                    )
                )
                provenance = list(
                    session.scalars(
                        select(ProvenanceRow)
                        .where(ProvenanceRow.resource_id == resource.resource_id)
                        .order_by(ProvenanceRow.provenance_id.asc())
                    )
                )
                exported_resources.append(
                    {
                        "resource_id": resource.resource_id,
                        "source_type": resource.source_type,
                        "canonical_uri": resource.canonical_uri,
                        "external_id": resource.external_id,
                        "content_hash": resource.content_hash,
                        "status": resource.status,
                        "first_seen_at": resource.first_seen_at,
                        "last_seen_at": resource.last_seen_at,
                        "metadata": dict(resource.metadata_json or {}),
                        "documents": exported_documents,
                        "records": [
                            {
                                "record_id": record.record_id,
                                "document_id": record.document_id,
                                "record_type": record.record_type,
                                "data": dict(record.data_json or {}) if include_content else None,
                                "revision": record.revision,
                                "review_status": record.review_status,
                                "metadata": dict(record.metadata_json or {}),
                            }
                            for record in records
                        ],
                        "provenance": [
                            {
                                "provenance_id": item.provenance_id,
                                "document_id": item.document_id,
                                "chunk_id": item.chunk_id,
                                "record_id": item.record_id,
                                "source_ref": item.source_ref,
                                "metadata": dict(item.metadata_json or {}),
                            }
                            for item in provenance
                        ],
                    }
                )

            return {
                "collection": _collection_payload(collection),
                "include_content": include_content,
                "offset": offset,
                "limit": limit,
                "total_resources": total_resources,
                "has_more": offset + len(resources) < total_resources,
                "resources": exported_resources,
            }

    def prune_collection_retention(
        self,
        collection_id: str,
        *,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        with self._require_factory()() as session:
            collection = session.get(CollectionRow, collection_id)
            if collection is None:
                raise CollectionNotFound(collection_id)
            policy = dict(collection.retention_policy or {})
            raw_days = policy.get("max_age_days")
            if raw_days is None:
                raise ValueError("collection retention max_age_days is not configured")
            max_age_days = int(raw_days)
            if max_age_days < 1:
                raise ValueError("collection retention max_age_days must be positive")
            cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
            resources = list(
                session.scalars(
                    select(ResourceRow)
                    .where(
                        ResourceRow.collection_id == collection_id,
                        ResourceRow.last_seen_at < cutoff,
                    )
                    .order_by(ResourceRow.resource_id.asc())
                )
            )
            if not dry_run:
                for resource in resources:
                    session.delete(resource)
                session.commit()
            return {
                "collection_id": collection_id,
                "dry_run": dry_run,
                "max_age_days": max_age_days,
                "cutoff_at": cutoff,
                "matched_resources": len(resources),
                "deleted_resources": 0 if dry_run else len(resources),
            }

    def delete_collection(
        self,
        collection_id: str,
        *,
        confirm: bool = False,
    ) -> dict[str, Any]:
        counts = self.collection_stats(collection_id)
        owned_counts = {
            key: int(counts[key])
            for key in ("resources", "documents", "chunks", "embeddings")
        }
        if not confirm:
            return {
                "collection_id": collection_id,
                "confirmed": False,
                "deleted": False,
                "counts": owned_counts,
            }
        with self._require_factory()() as session:
            collection = session.get(CollectionRow, collection_id)
            if collection is None:
                raise CollectionNotFound(collection_id)
            session.delete(collection)
            session.commit()
        return {
            "collection_id": collection_id,
            "confirmed": True,
            "deleted": True,
            "counts": owned_counts,
        }

    def collection_stats(self, collection_id: str) -> dict[str, Any]:
        with self._require_factory()() as session:
            if session.get(CollectionRow, collection_id) is None:
                raise CollectionNotFound(collection_id)

            resource_ids = select(ResourceRow.resource_id).where(
                ResourceRow.collection_id == collection_id
            )
            document_ids = select(DocumentRow.document_id).where(
                DocumentRow.resource_id.in_(resource_ids)
            )
            chunk_ids = select(ChunkRow.chunk_id).where(
                ChunkRow.document_id.in_(document_ids)
            )

            resources = session.scalar(
                select(func.count()).select_from(ResourceRow).where(
                    ResourceRow.collection_id == collection_id
                )
            ) or 0
            documents = session.scalar(
                select(func.count()).select_from(DocumentRow).where(
                    DocumentRow.resource_id.in_(resource_ids)
                )
            ) or 0
            chunks = session.scalar(
                select(func.count()).select_from(ChunkRow).where(
                    ChunkRow.document_id.in_(document_ids)
                )
            ) or 0
            embeddings = session.scalar(
                select(func.count()).select_from(ChunkEmbeddingRow).where(
                    ChunkEmbeddingRow.chunk_id.in_(chunk_ids)
                )
            ) or 0
            first_seen_at = session.scalar(
                select(func.min(ResourceRow.first_seen_at)).where(
                    ResourceRow.collection_id == collection_id
                )
            )
            last_seen_at = session.scalar(
                select(func.max(ResourceRow.last_seen_at)).where(
                    ResourceRow.collection_id == collection_id
                )
            )
            latest_embedding_at = session.scalar(
                select(func.max(ChunkEmbeddingRow.created_at)).where(
                    ChunkEmbeddingRow.chunk_id.in_(chunk_ids)
                )
            )
            latest_reindex_completed_at = session.scalar(
                select(func.max(PipelineRunRow.completed_at)).where(
                    PipelineRunRow.collection_id == collection_id,
                    PipelineRunRow.run_type == "reindex",
                    PipelineRunRow.status == "completed",
                )
            )
            collection = session.get(CollectionRow, collection_id)
            return {
                "collection_id": collection_id,
                "resources": int(resources),
                "documents": int(documents),
                "chunks": int(chunks),
                "embeddings": int(embeddings),
                "first_seen_at": first_seen_at,
                "last_seen_at": last_seen_at,
                "latest_embedding_at": latest_embedding_at,
                "latest_reindex_completed_at": latest_reindex_completed_at,
                "active_index_revision": (
                    collection.active_index_revision if collection else None
                ),
            }

    def process_document_bytes(
        self,
        *,
        collection_id: str,
        filename: str,
        content: bytes,
        title: str | None = None,
        canonical_uri: str | None = None,
        chunk_size_chars: int = 1500,
        overlap_chars: int = 200,
        min_chunk_chars: int = 120,
        max_chars: int = 2_000_000,
    ) -> dict[str, Any]:
        suffix = Path(filename).suffix[:16]
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
                handle.write(content)
                temporary_path = handle.name
            result = ingest_file(
                temporary_path,
                collection_id=collection_id,
                canonical_uri=canonical_uri or f"upload://{filename}",
                title=title or filename,
                chunking=ChunkingConfig(
                    chunk_size_chars=max(1, int(chunk_size_chars)),
                    overlap_chars=max(0, int(overlap_chars)),
                    min_chunk_chars=max(1, int(min_chunk_chars)),
                ),
                max_chars=max(1, int(max_chars)),
                ocr_provider=self.ocr_provider,
                vision_provider=self.model_router.provider(ModelRole.VISION),
            )
            return {
                "collection_id": result.resource.collection_id,
                "resource_id": result.resource.resource_id,
                "document_id": result.document.document_id,
                "canonical_uri": result.resource.canonical_uri,
                "title": result.document.title,
                "media_type": result.document.media_type,
                "extraction_status": result.document.extraction_status,
                "text": result.document.text,
                "chunks": [
                    {
                        "chunk_id": chunk.chunk_id,
                        "ordinal": chunk.ordinal,
                        "text": chunk.text,
                        "content_hash": chunk.content_hash,
                        "char_start": chunk.char_start,
                        "char_end": chunk.char_end,
                        "token_estimate": chunk.token_estimate,
                    }
                    for chunk in result.chunks
                ],
            }
        finally:
            if temporary_path:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass

    def ingest_document_bytes(
        self,
        *,
        collection_id: str,
        filename: str,
        content: bytes,
        title: str | None = None,
        canonical_uri: str | None = None,
        pre_chunked: bool = False,
    ) -> dict[str, Any]:
        suffix = Path(filename).suffix[:16]
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
                handle.write(content)
                temporary_path = handle.name
            result = ingest_file(
                temporary_path,
                collection_id=collection_id,
                canonical_uri=canonical_uri or f"upload://{filename}",
                title=title or filename,
                pre_chunked=pre_chunked,
                ocr_provider=self.ocr_provider,
                vision_provider=self.model_router.provider(ModelRole.VISION),
            )
            return self._persist_and_index(result)
        finally:
            if temporary_path:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass

    def ingest_url(
        self,
        *,
        collection_id: str,
        url: str,
        title: str | None = None,
    ) -> dict[str, Any]:
        if not self.settings.allow_private_fetches:
            validate_public_url(url)
        result = ingest_url(
            url,
            collection_id=collection_id,
            title=title,
            acquisition=self.acquisition,
        )
        return self._persist_and_index(result)

    def write_memory(
        self,
        *,
        collection_id: str,
        text: str,
        kind: MemoryKind | str,
        producer: str,
        consumer: str | None,
        title: str = "Memory",
        source_chunk_ids: Sequence[str] = (),
        model_provider: str | None = None,
        model_name: str | None = None,
        model_version: str | None = None,
        subject_key: str | None = None,
        conflict_policy: MemoryConflictPolicy | str = MemoryConflictPolicy.APPEND,
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        resolved_kind = MemoryKind(kind)
        resolved_conflict = MemoryConflictPolicy(conflict_policy)
        with self._require_factory()() as session:
            collection = session.get(CollectionRow, collection_id)
            if collection is None:
                raise CollectionNotFound(collection_id)
            self._authorize_collection_consumer(collection, consumer, session=session)
            policy = dict(collection.access_policy or {})
            writers = tuple(str(x) for x in policy.get("memory_writers", []) if str(x))
            user_writers = tuple(str(x) for x in policy.get("user_memory_writers", []) if str(x))
            if resolved_kind is MemoryKind.USER_MEMORY:
                if consumer not in user_writers:
                    raise CollectionAccessDenied(collection_id)
            elif consumer not in writers:
                raise CollectionAccessDenied(collection_id)
            if producer != consumer:
                raise CollectionAccessDenied(collection_id)

            source_ids = tuple(dict.fromkeys(str(x) for x in source_chunk_ids if str(x)))
            source_rows = []
            if source_ids:
                source_rows = session.scalars(
                    select(ChunkRow).where(ChunkRow.chunk_id.in_(source_ids))
                ).all()
                if len(source_rows) != len(source_ids):
                    raise ValueError("all source_chunk_ids must exist")
                for chunk in source_rows:
                    source_collection = session.scalar(
                        select(ResourceRow.collection_id)
                        .join(DocumentRow, DocumentRow.resource_id == ResourceRow.resource_id)
                        .where(DocumentRow.document_id == chunk.document_id)
                    )
                    source = session.get(CollectionRow, source_collection)
                    self._authorize_collection_consumer(source, consumer, session=session)

            if resolved_kind in {MemoryKind.SOURCE_EVIDENCE, MemoryKind.AGENT_OBSERVATION} and not source_ids:
                raise ValueError("evidence and agent observations require source_chunk_ids")
            if resolved_kind is MemoryKind.SOURCE_EVIDENCE and not any(
                text.strip() in source.text for source in source_rows
            ):
                raise ValueError("source_evidence text must be an exact excerpt of a source chunk")

            active_conflict = None
            if subject_key:
                active_conflict = session.scalar(
                    select(DataRecordRow)
                    .join(ResourceRow, ResourceRow.resource_id == DataRecordRow.resource_id)
                    .where(
                        ResourceRow.collection_id == collection_id,
                        DataRecordRow.record_type == "agent_memory",
                        DataRecordRow.data_json["subject_key"].as_string() == subject_key,
                        DataRecordRow.review_status == "active",
                    )
                    .order_by(DataRecordRow.created_at.desc())
                    .limit(1)
                )
            if active_conflict is not None and resolved_conflict is MemoryConflictPolicy.REJECT:
                raise ValueError("active memory already exists for subject_key")
            active_conflict_id = (
                active_conflict.record_id if active_conflict is not None else None
            )

        write = MemoryWrite(
            collection_id=collection_id,
            text=text,
            kind=resolved_kind,
            producer=producer,
            title=title,
            source_chunk_ids=source_ids,
            model_provider=model_provider,
            model_name=model_name,
            model_version=model_version,
            subject_key=subject_key,
            conflict_policy=resolved_conflict,
            metadata=metadata,
        )
        result = build_memory_ingest(write)
        indexed = self._persist_and_index(result)

        with self._require_factory()() as session:
            if active_conflict_id is not None and resolved_conflict is MemoryConflictPolicy.SUPERSEDE:
                previous = session.get(DataRecordRow, active_conflict_id)
                if previous is not None:
                    previous.review_status = "superseded"
            record = DataRecordRow(
                record_id=f"memory:{result.resource.resource_id}",
                resource_id=result.resource.resource_id,
                document_id=result.document.document_id,
                record_type="agent_memory",
                data_json={
                    "text": text,
                    "kind": resolved_kind.value,
                    "producer": producer,
                    "subject_key": subject_key,
                    "source_chunk_ids": list(source_ids),
                    "model": {
                        "provider": model_provider,
                        "name": model_name,
                        "version": model_version,
                    },
                },
                review_status="active",
                metadata_json=dict(metadata or {}),
            )
            session.add(record)
            for source in source_rows:
                session.add(
                    ProvenanceRow(
                        resource_id=result.resource.resource_id,
                        document_id=result.document.document_id,
                        record_id=record.record_id,
                        chunk_id=source.chunk_id,
                        source_ref=f"chunk:{source.chunk_id}",
                        excerpt=source.text[:1000],
                        metadata_json={"relation": "derived_from"},
                    )
                )
            session.commit()
        return {
            **indexed,
            "record_id": record.record_id,
            "kind": resolved_kind.value,
            "producer": producer,
            "subject_key": subject_key,
            "source_chunk_ids": list(source_ids),
        }

    def delete_memory(
        self, record_id: str, *, consumer: str | None
    ) -> None:
        with self._require_factory()() as session:
            record = session.get(DataRecordRow, record_id)
            if record is None or record.record_type != "agent_memory":
                raise MemoryNotFound(record_id)
            resource = session.get(ResourceRow, record.resource_id)
            collection = session.get(CollectionRow, resource.collection_id)
            self._authorize_collection_consumer(collection, consumer, session=session)
            policy = dict(collection.access_policy or {})
            writers = {
                str(x) for x in (
                    list(policy.get("memory_writers", []))
                    + list(policy.get("user_memory_writers", []))
                ) if str(x)
            }
            if consumer not in writers:
                raise CollectionAccessDenied(collection.collection_id)
            session.delete(resource)
            session.commit()

    def configure_resource_refresh(
        self,
        resource_id: str,
        *,
        interval_seconds: int = 86400,
        missing_after_failures: int = 3,
        enabled: bool = True,
    ) -> dict[str, Any]:
        policy = RefreshPolicy(interval_seconds, missing_after_failures, enabled)
        with self._require_factory()() as session:
            resource = session.get(ResourceRow, resource_id)
            if resource is None:
                raise LookupError(resource_id)
            if resource.source_type != "url":
                raise ValueError("continuous refresh currently supports URL resources only")
            resource.refresh_policy = policy.as_dict()
            resource.next_refresh_at = policy.next_at()
            session.commit()
            return {
                "resource_id": resource.resource_id,
                "refresh_policy": dict(resource.refresh_policy),
                "next_refresh_at": resource.next_refresh_at,
                "status": resource.status,
            }

    def refresh_resource(self, resource_id: str) -> RefreshResult:
        now = datetime.now(UTC)
        with self._require_factory()() as session:
            resource = session.get(ResourceRow, resource_id)
            if resource is None:
                raise LookupError(resource_id)
            if resource.source_type != "url":
                raise ValueError("continuous refresh currently supports URL resources only")
            policy = RefreshPolicy.from_mapping(resource.refresh_policy)
            previous_hash = resource.content_hash
            collection_id = resource.collection_id
            url = resource.canonical_uri
            title = None
            latest_document = session.scalar(
                select(DocumentRow)
                .where(DocumentRow.resource_id == resource_id)
                .order_by(DocumentRow.created_at.desc())
                .limit(1)
            )
            if latest_document is not None:
                title = latest_document.title
            run = RefreshRunRow(
                resource_id=resource_id,
                started_at=now,
                outcome="running",
                previous_hash=previous_hash,
                detail_json={},
            )
            session.add(run)
            session.commit()
            run_id = run.refresh_run_id

        try:
            if not self.settings.allow_private_fetches:
                validate_public_url(url)
            candidate = ingest_url(
                url,
                collection_id=collection_id,
                title=title,
                acquisition=self.acquisition,
            )
            current_hash = candidate.resource.content_hash
            if current_hash == previous_hash:
                with self._require_factory()() as session:
                    resource = session.get(ResourceRow, resource_id)
                    run = session.get(RefreshRunRow, run_id)
                    resource.last_seen_at = now
                    resource.status = "ready"
                    resource.etag = candidate.resource.metadata.get("etag")
                    resource.last_modified = candidate.resource.metadata.get("last_modified")
                    resource.next_refresh_at = policy.next_at(now)
                    run.outcome = "unchanged"
                    run.current_hash = current_hash
                    run.completed_at = datetime.now(UTC)
                    session.commit()
                    return RefreshResult(
                        run_id, resource_id, "unchanged", False, previous_hash,
                        current_hash, resource.next_refresh_at, {},
                    )
            indexed = self._persist_and_index(candidate)
            with self._require_factory()() as session:
                resource = session.get(ResourceRow, resource_id)
                run = session.get(RefreshRunRow, run_id)
                resource.next_refresh_at = policy.next_at(now)
                run.outcome = "changed"
                run.current_hash = current_hash
                run.completed_at = datetime.now(UTC)
                run.detail_json = {
                    "document_id": indexed["document_id"],
                    "embeddings_written": indexed["embeddings_written"],
                }
                session.commit()
                return RefreshResult(
                    run_id, resource_id, "changed", True, previous_hash,
                    current_hash, resource.next_refresh_at, dict(run.detail_json),
                )
        except Exception as exc:
            with self._require_factory()() as session:
                resource = session.get(ResourceRow, resource_id)
                run = session.get(RefreshRunRow, run_id)
                previous_failures = int(
                    (resource.metadata_json or {}).get("consecutive_refresh_failures", 0)
                )
                failures = previous_failures + 1
                metadata = dict(resource.metadata_json or {})
                metadata["consecutive_refresh_failures"] = failures
                resource.metadata_json = metadata
                resource.status = (
                    "stale" if failures >= policy.missing_after_failures else "refresh_error"
                )
                resource.next_refresh_at = policy.next_at(now)
                run.outcome = resource.status
                run.completed_at = datetime.now(UTC)
                run.detail_json = {"error_type": type(exc).__name__}
                session.commit()
            return RefreshResult(
                run_id, resource_id, resource.status, False, previous_hash,
                None, resource.next_refresh_at, {"error_type": type(exc).__name__},
            )

    def refresh_due_resources(self, *, limit: int = 50) -> list[RefreshResult]:
        now = datetime.now(UTC)
        with self._require_factory()() as session:
            resource_ids = list(
                session.scalars(
                    select(ResourceRow.resource_id)
                    .where(
                        ResourceRow.next_refresh_at.is_not(None),
                        ResourceRow.next_refresh_at <= now,
                    )
                    .order_by(ResourceRow.next_refresh_at.asc())
                    .limit(max(1, min(limit, 200)))
                )
            )
        return [self.refresh_resource(resource_id) for resource_id in resource_ids]

    def list_refresh_runs(
        self, resource_id: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        with self._require_factory()() as session:
            rows = session.scalars(
                select(RefreshRunRow)
                .where(RefreshRunRow.resource_id == resource_id)
                .order_by(RefreshRunRow.started_at.desc())
                .limit(max(1, min(limit, 200)))
            ).all()
            return [
                {
                    "refresh_run_id": row.refresh_run_id,
                    "resource_id": row.resource_id,
                    "started_at": row.started_at,
                    "completed_at": row.completed_at,
                    "outcome": row.outcome,
                    "previous_hash": row.previous_hash,
                    "current_hash": row.current_hash,
                    "detail": dict(row.detail_json or {}),
                }
                for row in rows
            ]

    def _runtime_embedding_contract(self) -> tuple[str, str, int | None]:
        return (
            self.embedding_provider.provider_name,
            self.embedding_provider.model_name,
            self.embedding_provider.dimension,
        )

    @staticmethod
    def _collection_embedding_contract(
        collection: CollectionRow,
    ) -> tuple[str | None, str | None, int | None]:
        return (
            collection.embedding_provider,
            collection.embedding_model,
            collection.embedding_dimension,
        )

    def _embedding_contract_matches(self, collection: CollectionRow) -> bool:
        expected_provider, expected_model, expected_dimension = (
            self._collection_embedding_contract(collection)
        )
        actual_provider, actual_model, actual_dimension = self._runtime_embedding_contract()
        if expected_provider != actual_provider or expected_model != actual_model:
            return False
        if (
            expected_dimension is not None
            and actual_dimension is not None
            and expected_dimension != actual_dimension
        ):
            return False
        return True

    def _validate_embedding_contract(self, collection: CollectionRow) -> None:
        if not self._embedding_contract_matches(collection):
            raise EmbeddingContractMismatch(
                f"collection {collection.collection_id!r} embedding contract "
                f"{self._collection_embedding_contract(collection)!r} does not match runtime "
                f"{self._runtime_embedding_contract()!r}; run an explicit index rebuild to migrate"
            )

    def _resolve_target_embedding_dimension(
        self,
        repo: DataRepository,
        collection_id: str,
        *,
        vectors: Sequence[Sequence[float]] | None = None,
    ) -> int | None:
        if vectors:
            dimensions = {len(vector) for vector in vectors}
            if len(dimensions) != 1:
                raise EmbeddingContractMismatch(
                    f"embedding provider returned inconsistent dimensions: {sorted(dimensions)}"
                )
            dimension = dimensions.pop()
            if self.embedding_provider.dimension is None:
                self.embedding_provider.dimension = dimension
            elif self.embedding_provider.dimension != dimension:
                raise EmbeddingContractMismatch(
                    f"runtime embedding dimension {self.embedding_provider.dimension} "
                    f"does not match generated dimension {dimension}"
                )
            return dimension
        if self.embedding_provider.dimension is not None:
            return int(self.embedding_provider.dimension)
        dimensions = repo.embedding_dimensions(
            collection_id,
            provider=self.embedding_provider.provider_name,
            model=self.embedding_provider.model_name,
        )
        if len(dimensions) == 1:
            return next(iter(dimensions))
        if len(dimensions) > 1:
            raise EmbeddingContractMismatch(
                f"multiple embedding dimensions exist for target model: {sorted(dimensions)}"
            )
        return None

    def _embed_texts_with_retry(
        self,
        texts: list[str],
    ) -> tuple[list[list[float]], int]:
        if not texts:
            return [], 0
        max_attempts = self.settings.embedding_retry_max_attempts
        for attempt in range(1, max_attempts + 1):
            try:
                return self.embedding_provider.embed_texts(texts), attempt
            except EmbeddingServerUnavailableError:
                if attempt >= max_attempts:
                    raise
                delay = min(
                    self.settings.embedding_retry_max_delay_seconds,
                    self.settings.embedding_retry_base_delay_seconds
                    * (2 ** (attempt - 1)),
                )
                if delay > 0:
                    time.sleep(delay)
        raise RuntimeError("embedding retry loop exited unexpectedly")

    def _persist_and_index(self, result) -> dict[str, Any]:
        if len(result.chunks) > self.settings.max_chunks_per_ingest:
            raise ValueError(
                "ingest exceeds max_chunks_per_ingest="
                f"{self.settings.max_chunks_per_ingest}"
            )
        with self._require_factory()() as session:
            collection = session.get(CollectionRow, result.resource.collection_id)
            if collection is None:
                raise CollectionNotFound(result.resource.collection_id)
            self._validate_embedding_contract(collection)

            repo = DataRepository(session)
            existing_embedding_ids = repo.existing_embedding_chunk_ids(
                [chunk.chunk_id for chunk in result.chunks],
                provider=self.embedding_provider.provider_name,
                model=self.embedding_provider.model_name,
            )
            repo.persist_ingest(result)
            pending_chunks = [
                chunk
                for chunk in result.chunks
                if chunk.chunk_id not in existing_embedding_ids
            ]
            vectors, embedding_attempts = self._embed_texts_with_retry(
                [chunk.text for chunk in pending_chunks]
            )
            if len(vectors) != len(pending_chunks):
                raise RuntimeError("embedding provider returned unexpected vector count")
            for chunk, vector in zip(pending_chunks, vectors):
                repo.upsert_embedding(
                    chunk_id=chunk.chunk_id,
                    provider=self.embedding_provider.provider_name,
                    model=self.embedding_provider.model_name,
                    vector=vector,
                )
            if vectors:
                dimension = len(vectors[0])
                if collection.embedding_dimension is None:
                    collection.embedding_dimension = dimension
                elif collection.embedding_dimension != dimension:
                    raise EmbeddingContractMismatch(
                        f"collection {collection.collection_id!r} expects "
                        f"dimension {collection.embedding_dimension}, got {dimension}"
                    )
            session.commit()

            return {
                "collection_id": result.resource.collection_id,
                "resource_id": result.resource.resource_id,
                "document_id": result.document.document_id,
                "chunks": len(result.chunks),
                "chunks_indexed": len(result.chunks),
                "embeddings": len(result.chunks),
                "embeddings_written": len(vectors),
                "embeddings_skipped_existing": len(existing_embedding_ids),
                "embedding_attempts": embedding_attempts,
                "canonical_uri": result.resource.canonical_uri,
                "extraction_status": result.document.extraction_status,
            }

    @staticmethod
    def _collapse_canonical_hits(
        hits: Sequence[SearchHit],
        *,
        limit: int,
    ) -> list[SearchHit]:
        seen: set[str] = set()
        results: list[SearchHit] = []
        for hit in hits:
            canonical_uri = hit.canonical_uri.strip()
            key = canonical_uri or hit.chunk_id
            if key in seen:
                continue
            seen.add(key)
            results.append(hit)
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _dedupe_federated_hits(
        hits: Sequence[SearchHit],
        *,
        limit: int,
    ) -> list[SearchHit]:
        winners: dict[str, str] = {}
        results: list[SearchHit] = []
        for hit in hits:
            canonical_uri = hit.canonical_uri.strip()
            collection_id = str(hit.metadata.get("collection_id") or "")
            if canonical_uri and collection_id:
                winner = winners.get(canonical_uri)
                if winner is None:
                    winners[canonical_uri] = collection_id
                elif winner != collection_id:
                    continue
            results.append(hit)
            if len(results) >= limit:
                break
        return results

    def search(
        self,
        request: SearchQuery,
        *,
        consumer: str | None = None,
    ) -> list[SearchHit]:
        hits, _ = self.search_with_diagnostics(request, consumer=consumer)
        return hits

    def search_with_diagnostics(
        self,
        request: SearchQuery,
        *,
        consumer: str | None = None,
    ) -> tuple[list[SearchHit], tuple[QueryExpansion, ...]]:
        hits, expansions, _ = self.search_with_execution_diagnostics(
            request,
            consumer=consumer,
        )
        return hits, expansions

    def search_with_execution_diagnostics(
        self,
        request: SearchQuery,
        *,
        consumer: str | None = None,
    ) -> tuple[
        list[SearchHit],
        tuple[QueryExpansion, ...],
        tuple[SearchStageDiagnostic, ...],
    ]:
        self._validate_tenant_search_quota(request, consumer)
        with self._require_factory()() as session:
            for collection_id in request.collections:
                collection = session.get(CollectionRow, collection_id)
                if collection is None:
                    raise CollectionNotFound(collection_id)
                self._authorize_collection_consumer(collection, consumer, session=session)
                self._validate_embedding_contract(collection)

            backend = PostgresSearchBackend(DataRepository(session))
            reasoning_provider = self.model_router.provider(ModelRole.REASONING)
            reranker = None
            if request.rerank:
                if request.rerank_strategy is RerankStrategy.CROSS_ENCODER:
                    reranker = self._cross_encoder_reranker(
                        max_candidates=request.rerank_candidates,
                    )
                elif reasoning_provider is not None:
                    reranker = ReasoningReranker(
                        reasoning_provider,
                        max_candidates=request.rerank_candidates,
                    )
            query_expander = (
                ReasoningQueryExpander(reasoning_provider)
                if request.expand_query and reasoning_provider is not None
                else None
            )
            engine = HybridSearchEngine(
                lexical_backend=backend,
                vector_backend=backend,
                embedding_provider=self.embedding_provider,
                reranker=reranker,
                query_expander=query_expander,
            )
            if len(request.collections) == 1 and not request.collapse_by_canonical_uri:
                hits = engine.search(request)
                return hits, engine.last_expansions, engine.last_diagnostics

            overfetch_factor = (
                4
                if request.collapse_by_canonical_uri
                else min(max(len(request.collections), 2), 8)
            )
            expanded_limit = min(100, request.limit * overfetch_factor)
            expanded_rerank_candidates = max(
                request.rerank_candidates,
                expanded_limit,
            )
            if request.execution_mode is not None and request.rerank:
                profile = mode_profile(request.execution_mode)
                expanded_limit = min(
                    expanded_limit,
                    profile.max_rerank_candidates,
                )
                expanded_rerank_candidates = min(
                    expanded_rerank_candidates,
                    profile.max_rerank_candidates,
                )

            expanded_request = SearchQuery(
                query=request.query,
                collections=request.collections,
                filters=request.filters,
                limit=expanded_limit,
                mode=request.mode,
                lexical_weight=request.lexical_weight,
                vector_weight=request.vector_weight,
                query_variants=request.query_variants,
                query_variant_weight=request.query_variant_weight,
                expand_query=request.expand_query,
                query_expansion_limit=request.query_expansion_limit,
                collapse_by_canonical_uri=request.collapse_by_canonical_uri,
                rerank=request.rerank,
                rerank_candidates=expanded_rerank_candidates,
                rerank_strategy=request.rerank_strategy,
                execution_mode=request.execution_mode,
            )
            hits = engine.search(expanded_request)
            if request.collapse_by_canonical_uri:
                collapsed = self._collapse_canonical_hits(
                    hits,
                    limit=request.limit,
                )
                return collapsed, engine.last_expansions, engine.last_diagnostics
            return (
                self._dedupe_federated_hits(hits, limit=request.limit),
                engine.last_expansions,
                engine.last_diagnostics,
            )


    def answer(
        self,
        request: SearchQuery,
        *,
        consumer: str | None = None,
    ) -> tuple[GroundedAnswer, list[SearchHit]]:
        hits = self.search(request, consumer=consumer)
        reasoning_provider = self.model_router.provider(ModelRole.REASONING)
        if reasoning_provider is None:
            return (
                GroundedAnswer(
                    answer=None,
                    claims=(),
                    contradictions=(),
                    uncertainty="Reasoning provider is not configured.",
                    abstained=True,
                ),
                hits,
            )
        try:
            answer = ReasoningAnswerSynthesizer(
                reasoning_provider,
                max_hits=request.limit,
            ).synthesize(request.query, hits)
        except Exception as exc:
            answer = GroundedAnswer(
                answer=None,
                claims=(),
                contradictions=(),
                uncertainty=f"Synthesis unavailable: {type(exc).__name__}.",
                abstained=True,
            )
        return answer, hits


    def research(
        self,
        *,
        query: str,
        collection_id: str,
        connector: str = "duckduckgo_html",
        source_limit: int = 8,
        evidence_limit: int = 8,
        consumer: str | None = None,
        rerank: bool = False,
        expand_query: bool = False,
    ) -> ResearchResult:
        return ResearchWorkflow(self).run(
            query=query,
            collection_id=collection_id,
            connector=connector,
            source_limit=source_limit,
            evidence_limit=evidence_limit,
            consumer=consumer,
            rerank=rerank,
            expand_query=expand_query,
        )



    def _index_revision(
        self,
        collection: CollectionRow,
        chunks: Sequence[ChunkRow],
    ) -> str:
        payload = "\n".join(
            [
                f"provider={self.embedding_provider.provider_name}",
                f"model={self.embedding_provider.model_name}",
                f"dimension={self.embedding_provider.dimension}",
                f"language={collection.default_language}",
                *[
                    f"{chunk.chunk_id}:{chunk.content_hash}"
                    for chunk in sorted(chunks, key=lambda item: item.chunk_id)
                ],
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _job_payload(row: PipelineRunRow) -> dict[str, Any]:
        return {
            "run_id": row.run_id,
            "collection_id": row.collection_id,
            "run_type": row.run_type,
            "revision": row.revision,
            "status": row.status,
            "metrics": dict(row.metrics_json or {}),
            "started_at": row.started_at,
            "completed_at": row.completed_at,
        }

    def rebuild_index(self, collection_id: str) -> dict[str, Any]:
        factory = self._require_factory()
        run_id = str(uuid.uuid4())

        with factory() as session:
            collection = session.get(CollectionRow, collection_id)
            if collection is None:
                raise CollectionNotFound(collection_id)
            chunks = list(
                session.scalars(
                    select(ChunkRow)
                    .join(DocumentRow, DocumentRow.document_id == ChunkRow.document_id)
                    .join(ResourceRow, ResourceRow.resource_id == DocumentRow.resource_id)
                    .where(ResourceRow.collection_id == collection_id)
                    .order_by(ChunkRow.chunk_id.asc())
                )
            )
            revision = self._index_revision(collection, chunks)
            existing_run = session.scalar(
                select(PipelineRunRow)
                .where(
                    PipelineRunRow.collection_id == collection_id,
                    PipelineRunRow.run_type == "reindex",
                    PipelineRunRow.revision == revision,
                )
                .limit(1)
            )

            if existing_run is not None:
                if (
                    collection.active_index_revision == revision
                    and existing_run.status == "completed"
                ):
                    return self._job_payload(existing_run)
                if existing_run.status in {"failed", "dead_letter"}:
                    run = existing_run
                    run_id = run.run_id
                    run.status = "running"
                    run.metrics_json = {}
                    run.started_at = datetime.now(UTC)
                    run.completed_at = None
                elif existing_run.status == "running":
                    return self._job_payload(existing_run)
                elif existing_run.status == "completed":
                    repo = DataRepository(session)
                    target_dimension = self._resolve_target_embedding_dimension(
                        repo,
                        collection_id,
                    )
                    repo.activate_collection_embedding(
                        collection_id,
                        provider=self.embedding_provider.provider_name,
                        model=self.embedding_provider.model_name,
                        dimension=target_dimension,
                        require_complete=True,
                    )
                    collection.active_index_revision = revision
                    session.commit()
                    return self._job_payload(existing_run)
                else:
                    raise RuntimeError(
                        f"unsupported reindex job status: {existing_run.status}"
                    )
            else:
                run = PipelineRunRow(
                    run_id=run_id,
                    collection_id=collection_id,
                    run_type="reindex",
                    revision=revision,
                    status="running",
                    metrics_json={},
                    started_at=datetime.now(UTC),
                )
                session.add(run)

            session.commit()

        try:
            with factory() as session:
                collection = session.get(CollectionRow, collection_id)
                if collection is None:
                    raise CollectionNotFound(collection_id)
                chunks = list(
                    session.scalars(
                        select(ChunkRow)
                        .join(DocumentRow, DocumentRow.document_id == ChunkRow.document_id)
                        .join(ResourceRow, ResourceRow.resource_id == DocumentRow.resource_id)
                        .where(ResourceRow.collection_id == collection_id)
                        .order_by(ChunkRow.chunk_id.asc())
                    )
                )
                current_revision = self._index_revision(collection, chunks)
                if current_revision != revision:
                    raise RuntimeError("collection changed before reindex execution")

                vectors, embedding_attempts = self._embed_texts_with_retry(
                    [chunk.text for chunk in chunks]
                )
                if len(vectors) != len(chunks):
                    raise RuntimeError("embedding provider returned unexpected vector count")

                repo = DataRepository(session)
                target_dimension = self._resolve_target_embedding_dimension(
                    repo,
                    collection_id,
                    vectors=vectors,
                )
                previous_contract = self._collection_embedding_contract(collection)
                for chunk, vector in zip(chunks, vectors):
                    repo.upsert_embedding(
                        chunk_id=chunk.chunk_id,
                        provider=self.embedding_provider.provider_name,
                        model=self.embedding_provider.model_name,
                        vector=vector,
                    )

                final_chunks = list(
                    session.scalars(
                        select(ChunkRow)
                        .join(DocumentRow, DocumentRow.document_id == ChunkRow.document_id)
                        .join(ResourceRow, ResourceRow.resource_id == DocumentRow.resource_id)
                        .where(ResourceRow.collection_id == collection_id)
                        .order_by(ChunkRow.chunk_id.asc())
                    )
                )
                if self._index_revision(collection, final_chunks) != revision:
                    raise RuntimeError("collection changed during reindex execution")

                run = session.get(PipelineRunRow, run_id)
                if run is None:
                    raise RuntimeError("reindex run disappeared")
                repo.activate_collection_embedding(
                    collection_id,
                    provider=self.embedding_provider.provider_name,
                    model=self.embedding_provider.model_name,
                    dimension=target_dimension,
                    require_complete=True,
                )
                target_contract = self._collection_embedding_contract(collection)
                run.status = "completed"
                run.metrics_json = {
                    "chunks_seen": len(chunks),
                    "embeddings_written": len(vectors),
                    "embedding_attempts": embedding_attempts,
                    "skipped_unchanged": False,
                    "embedding_migration": previous_contract != target_contract,
                    "embedding_provider": target_contract[0],
                    "embedding_model": target_contract[1],
                    "embedding_dimension": target_contract[2],
                }
                run.completed_at = datetime.now(UTC)
                collection.active_index_revision = revision
                session.commit()
                return self._job_payload(run)
        except Exception as exc:
            dead_letter = isinstance(exc, EmbeddingServerUnavailableError)
            attempts = (
                self.settings.embedding_retry_max_attempts
                if dead_letter
                else 1
            )
            with factory() as session:
                run = session.get(PipelineRunRow, run_id)
                if run is not None:
                    run.status = "dead_letter" if dead_letter else "failed"
                    run.metrics_json = {
                        "error_type": type(exc).__name__,
                        "embedding_attempts": attempts,
                        "dead_letter": dead_letter,
                    }
                    run.completed_at = datetime.now(UTC)
                    session.commit()
            raise

    def get_index_job(self, run_id: str) -> dict[str, Any]:
        with self._require_factory()() as session:
            row = session.get(PipelineRunRow, run_id)
            if row is None:
                raise IndexJobNotFound(run_id)
            return self._job_payload(row)

    def list_index_jobs(
        self,
        *,
        collection_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._require_factory()() as session:
            statement = select(PipelineRunRow)
            if collection_id:
                statement = statement.where(
                    PipelineRunRow.collection_id == collection_id
                )
            statement = statement.order_by(
                PipelineRunRow.started_at.desc(),
                PipelineRunRow.run_id.asc(),
            ).limit(max(1, min(limit, 100)))
            return [self._job_payload(row) for row in session.scalars(statement)]

    @staticmethod
    def _entity_payload(entity: EntityRow) -> dict[str, Any]:
        aliases = sorted(
            entity.aliases,
            key=lambda item: (
                item.alias_kind,
                item.normalized_value,
                item.alias_id,
            ),
        )
        return {
            "entity_id": entity.entity_id,
            "entity_type": entity.entity_type,
            "canonical_name": entity.canonical_name,
            "aliases": [
                {
                    "alias_id": alias.alias_id,
                    "alias_kind": alias.alias_kind,
                    "value": alias.alias_value,
                    "normalized_value": alias.normalized_value,
                    "source_collection_id": alias.source_collection_id,
                    "metadata": dict(alias.metadata_json or {}),
                    "created_at": alias.created_at,
                }
                for alias in aliases
            ],
            "metadata": dict(entity.metadata_json or {}),
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
        }

    def create_entity(
        self,
        *,
        entity_type: str,
        canonical_name: str,
        aliases: Sequence[Mapping[str, object]] = (),
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        normalized_canonical = normalize_entity_value(canonical_name)
        if not normalized_canonical:
            raise ValueError("canonical entity name is empty after normalization")

        with self._require_factory()() as session:
            entity = EntityRow(
                entity_type=entity_type.strip(),
                canonical_name=canonical_name.strip(),
                metadata_json=dict(metadata or {}),
            )
            session.add(entity)
            session.flush()

            alias_specs: list[dict[str, object]] = [
                {
                    "alias_kind": "name",
                    "value": canonical_name,
                    "source_collection_id": None,
                    "metadata": {"canonical": True},
                }
            ]
            alias_specs.extend(dict(item) for item in aliases)

            seen: set[tuple[str, str]] = set()
            for spec in alias_specs:
                kind = str(spec.get("alias_kind") or "").strip()
                value = str(spec.get("value") or "").strip()
                normalized = normalize_entity_value(value)
                if not kind or not normalized:
                    raise ValueError("entity alias kind and value are required")
                identity = (kind, normalized)
                if identity in seen:
                    continue
                seen.add(identity)

                source_collection_id = spec.get("source_collection_id")
                if source_collection_id is not None:
                    source_collection_id = str(source_collection_id)
                    if session.get(CollectionRow, source_collection_id) is None:
                        raise CollectionNotFound(source_collection_id)

                session.add(
                    EntityAliasRow(
                        entity_id=entity.entity_id,
                        entity_type=entity.entity_type,
                        alias_kind=kind,
                        alias_value=value,
                        normalized_value=normalized,
                        source_collection_id=source_collection_id,
                        metadata_json=dict(spec.get("metadata") or {}),
                    )
                )

            session.commit()
            session.refresh(entity)
            _ = entity.aliases
            return self._entity_payload(entity)

    def get_entity(self, entity_id: str) -> dict[str, Any]:
        with self._require_factory()() as session:
            entity = session.get(EntityRow, entity_id)
            if entity is None:
                raise EntityNotFound(entity_id)
            _ = entity.aliases
            return self._entity_payload(entity)

    def resolve_entity(
        self,
        *,
        entity_type: str,
        value: str,
        alias_kind: str = "name",
        limit: int = 20,
    ) -> dict[str, Any]:
        normalized = normalize_entity_value(value)
        if not normalized:
            raise ValueError("entity value is empty after normalization")

        with self._require_factory()() as session:
            rows = (
                session.scalars(
                    select(EntityRow)
                    .join(
                        EntityAliasRow,
                        EntityAliasRow.entity_id == EntityRow.entity_id,
                    )
                    .where(
                        EntityAliasRow.entity_type == entity_type.strip(),
                        EntityAliasRow.alias_kind == alias_kind.strip(),
                        EntityAliasRow.normalized_value == normalized,
                    )
                    .order_by(
                        EntityRow.created_at.asc(),
                        EntityRow.entity_id.asc(),
                    )
                    .limit(max(1, min(limit, 100)))
                )
                .unique()
                .all()
            )
            for entity in rows:
                _ = entity.aliases
            status = (
                "unresolved"
                if not rows
                else "resolved"
                if len(rows) == 1
                else "ambiguous"
            )
            return {
                "status": status,
                "normalized_value": normalized,
                "candidates": [
                    self._entity_payload(entity)
                    for entity in rows
                ],
            }

    @staticmethod
    def _relation_payload(row: EntityRelationRow) -> dict[str, Any]:
        return {
            "relation_id": row.relation_id,
            "source_entity_id": row.source_entity_id,
            "target_entity_id": row.target_entity_id,
            "relation_type": row.relation_type,
            "status": row.status,
            "valid_from": row.valid_from,
            "valid_to": row.valid_to,
            "source_collection_id": row.source_collection_id,
            "resource_id": row.resource_id,
            "document_id": row.document_id,
            "chunk_id": row.chunk_id,
            "metadata": dict(row.metadata_json or {}),
            "created_at": row.created_at,
        }

    def create_entity_relation(
        self,
        *,
        source_entity_id: str,
        target_entity_id: str,
        relation_type: str,
        status: str = "canonical",
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        source_collection_id: str | None = None,
        resource_id: str | None = None,
        document_id: str | None = None,
        chunk_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        if source_entity_id == target_entity_id:
            raise ValueError("entity relation cannot target the same entity")
        normalized_type = relation_type.strip()
        if not normalized_type:
            raise ValueError("relation_type is required")
        normalized_status = status.strip().lower()
        if normalized_status not in {"canonical", "proposed", "rejected"}:
            raise ValueError("relation status must be canonical, proposed or rejected")
        if valid_from is not None and valid_to is not None and valid_to < valid_from:
            raise ValueError("valid_to must be greater than or equal to valid_from")
        if normalized_status == "proposed" and chunk_id is None:
            raise ValueError("proposed relations require chunk evidence")

        with self._require_factory()() as session:
            if session.get(EntityRow, source_entity_id) is None:
                raise EntityNotFound(source_entity_id)
            if session.get(EntityRow, target_entity_id) is None:
                raise EntityNotFound(target_entity_id)

            resolved_collection = source_collection_id
            resolved_resource = resource_id
            resolved_document = document_id
            resolved_chunk = chunk_id

            if resolved_chunk is not None:
                chunk = session.get(ChunkRow, resolved_chunk)
                if chunk is None:
                    raise ValueError("relation chunk does not exist")
                if resolved_document is not None and resolved_document != chunk.document_id:
                    raise ValueError("relation chunk/document mismatch")
                resolved_document = chunk.document_id

            if resolved_document is not None:
                document = session.get(DocumentRow, resolved_document)
                if document is None:
                    raise ValueError("relation document does not exist")
                if resolved_resource is not None and resolved_resource != document.resource_id:
                    raise ValueError("relation document/resource mismatch")
                resolved_resource = document.resource_id

            if resolved_resource is not None:
                resource = session.get(ResourceRow, resolved_resource)
                if resource is None:
                    raise ValueError("relation resource does not exist")
                if (
                    resolved_collection is not None
                    and resolved_collection != resource.collection_id
                ):
                    raise ValueError("relation resource/collection mismatch")
                resolved_collection = resource.collection_id
            elif resolved_collection is not None:
                if session.get(CollectionRow, resolved_collection) is None:
                    raise CollectionNotFound(resolved_collection)

            identity = "\n".join(
                [
                    source_entity_id,
                    target_entity_id,
                    normalized_type,
                    resolved_collection or "",
                    resolved_resource or "",
                    resolved_document or "",
                    resolved_chunk or "",
                ]
            )
            relation_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            existing = session.get(EntityRelationRow, relation_id)
            if existing is not None:
                return self._relation_payload(existing)

            row = EntityRelationRow(
                relation_id=relation_id,
                source_entity_id=source_entity_id,
                target_entity_id=target_entity_id,
                relation_type=normalized_type,
                status=normalized_status,
                valid_from=valid_from,
                valid_to=valid_to,
                source_collection_id=resolved_collection,
                resource_id=resolved_resource,
                document_id=resolved_document,
                chunk_id=resolved_chunk,
                metadata_json=dict(metadata or {}),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._relation_payload(row)

    def list_entity_relations(
        self,
        entity_id: str,
        *,
        direction: str = "both",
        relation_type: str | None = None,
        status: str | None = "canonical",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        normalized_direction = direction.strip().lower()
        if normalized_direction not in {"outbound", "inbound", "both"}:
            raise ValueError("direction must be outbound, inbound or both")

        with self._require_factory()() as session:
            if session.get(EntityRow, entity_id) is None:
                raise EntityNotFound(entity_id)

            statement = select(EntityRelationRow)
            if normalized_direction == "outbound":
                statement = statement.where(
                    EntityRelationRow.source_entity_id == entity_id
                )
            elif normalized_direction == "inbound":
                statement = statement.where(
                    EntityRelationRow.target_entity_id == entity_id
                )
            else:
                statement = statement.where(
                    or_(
                        EntityRelationRow.source_entity_id == entity_id,
                        EntityRelationRow.target_entity_id == entity_id,
                    )
                )
            if relation_type:
                statement = statement.where(
                    EntityRelationRow.relation_type == relation_type.strip()
                )
            if status is not None:
                normalized_status = status.strip().lower()
                if normalized_status not in {"canonical", "proposed", "rejected"}:
                    raise ValueError("relation status must be canonical, proposed or rejected")
                statement = statement.where(EntityRelationRow.status == normalized_status)
            statement = statement.order_by(
                EntityRelationRow.created_at.asc(),
                EntityRelationRow.relation_id.asc(),
            ).limit(max(1, min(limit, 500)))
            return [
                self._relation_payload(row)
                for row in session.scalars(statement).all()
            ]

    def suggest_graph_enrichment(
        self,
        *,
        query: str,
        collection_id: str,
        entity_ids: Sequence[str],
        evidence_limit: int = 8,
        consumer: str | None = None,
    ) -> GraphSuggestions:
        provider = self.model_router.provider(ModelRole.REASONING)
        if provider is None:
            return GraphSuggestions((), ())
        entities = [self.get_entity(entity_id) for entity_id in dict.fromkeys(entity_ids)]
        hits = self.search(
            SearchQuery(
                query=query,
                collections=(collection_id,),
                limit=max(1, min(evidence_limit, 20)),
            ),
            consumer=consumer,
        )
        return EvidenceGraphSuggester(provider).suggest(entities=entities, hits=hits)

    def review_entity_relation(
        self,
        relation_id: str,
        *,
        decision: str,
        reviewer: str | None = None,
    ) -> dict[str, Any]:
        normalized = decision.strip().lower()
        if normalized not in {"canonical", "rejected"}:
            raise ValueError("review decision must be canonical or rejected")
        with self._require_factory()() as session:
            row = session.get(EntityRelationRow, relation_id)
            if row is None:
                raise LookupError(relation_id)
            if row.status != "proposed":
                raise ValueError("only proposed relations can be reviewed")
            row.status = normalized
            metadata = dict(row.metadata_json or {})
            metadata["review"] = {"decision": normalized, "reviewer": reviewer}
            row.metadata_json = metadata
            session.commit()
            session.refresh(row)
            return self._relation_payload(row)

    def traverse_entity_graph(
        self,
        entity_id: str,
        *,
        max_depth: int = 2,
        relation_type: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        if max_depth < 1 or max_depth > 5:
            raise ValueError("max_depth must be between 1 and 5")
        frontier = {entity_id}
        visited = {entity_id}
        result: list[dict[str, Any]] = []
        seen_relations: set[str] = set()
        for depth in range(1, max_depth + 1):
            next_frontier: set[str] = set()
            for current in sorted(frontier):
                rows = self.list_entity_relations(
                    current,
                    direction="both",
                    relation_type=relation_type,
                    status="canonical",
                    limit=min(limit, 500),
                )
                for row in rows:
                    if row["relation_id"] in seen_relations:
                        continue
                    seen_relations.add(row["relation_id"])
                    enriched = dict(row)
                    enriched["depth"] = depth
                    result.append(enriched)
                    if len(result) >= limit:
                        return result
                    neighbor = (
                        row["target_entity_id"]
                        if row["source_entity_id"] == current
                        else row["source_entity_id"]
                    )
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_frontier.add(neighbor)
            frontier = next_frontier
            if not frontier:
                break
        return result

    @staticmethod
    def _feedback_payload(row: RelevanceFeedbackRow) -> dict[str, Any]:
        return {
            "feedback_id": row.feedback_id,
            "collection_id": row.collection_id,
            "resource_id": row.resource_id,
            "document_id": row.document_id,
            "chunk_id": row.chunk_id,
            "query_hash": row.query_hash,
            "label": row.label,
            "rank": row.rank,
            "actor": row.actor,
            "context": dict(row.context_json or {}),
            "created_at": row.created_at,
        }

    def record_relevance_feedback(
        self,
        *,
        collection_id: str,
        resource_id: str,
        document_id: str,
        chunk_id: str,
        query: str,
        label: str,
        rank: int | None = None,
        actor: str | None = None,
        context: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        allowed = {"relevant", "partially_relevant", "not_relevant"}
        if label not in allowed:
            raise ValueError("invalid relevance feedback label")
        query_hash = hashlib.sha256(query.strip().encode("utf-8")).hexdigest()

        with self._require_factory()() as session:
            chunk = session.get(ChunkRow, chunk_id)
            document = session.get(DocumentRow, document_id)
            resource = session.get(ResourceRow, resource_id)
            if chunk is None or document is None or resource is None:
                raise ValueError("feedback target does not exist")
            if chunk.document_id != document_id:
                raise ValueError("feedback chunk/document mismatch")
            if document.resource_id != resource_id:
                raise ValueError("feedback document/resource mismatch")
            if resource.collection_id != collection_id:
                raise ValueError("feedback target is outside the collection")

            row = RelevanceFeedbackRow(
                collection_id=collection_id,
                resource_id=resource_id,
                document_id=document_id,
                chunk_id=chunk_id,
                query_hash=query_hash,
                label=label,
                rank=rank,
                actor=actor,
                context_json=dict(context or {}),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._feedback_payload(row)

    def list_relevance_feedback(
        self,
        *,
        collection_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._require_factory()() as session:
            if session.get(CollectionRow, collection_id) is None:
                raise CollectionNotFound(collection_id)
            rows = session.scalars(
                select(RelevanceFeedbackRow)
                .where(RelevanceFeedbackRow.collection_id == collection_id)
                .order_by(
                    RelevanceFeedbackRow.created_at.desc(),
                    RelevanceFeedbackRow.feedback_id.desc(),
                )
                .limit(max(1, min(limit, 1000)))
            ).all()
            return [self._feedback_payload(row) for row in rows]

    def relevance_feedback_summary(self, collection_id: str) -> dict[str, Any]:
        with self._require_factory()() as session:
            if session.get(CollectionRow, collection_id) is None:
                raise CollectionNotFound(collection_id)
            counts = dict(
                session.execute(
                    select(
                        RelevanceFeedbackRow.label,
                        func.count(RelevanceFeedbackRow.feedback_id),
                    )
                    .where(RelevanceFeedbackRow.collection_id == collection_id)
                    .group_by(RelevanceFeedbackRow.label)
                ).all()
            )
            return {
                "collection_id": collection_id,
                "total": int(sum(counts.values())),
                "relevant": int(counts.get("relevant", 0)),
                "partially_relevant": int(counts.get("partially_relevant", 0)),
                "not_relevant": int(counts.get("not_relevant", 0)),
            }

    def extract_url(
        self,
        *,
        url: str,
        fields: Sequence[FieldSpec],
        use_model: bool = False,
    ):
        if not self.settings.allow_private_fetches:
            validate_public_url(url)
        providers = [AutoDiscoveryProvider()]
        reasoning_provider = self.model_router.provider(ModelRole.REASONING)
        if use_model and reasoning_provider is not None:
            providers.append(ReasoningCandidateProvider(reasoning_provider))
        pipeline = URLExtractionPipeline(
            acquisition=self.acquisition,
            providers=tuple(providers),
        )
        return pipeline.extract_url(url, fields)

    def extract(
        self,
        *,
        asset_id: str,
        source_url: str | None,
        text: str | None,
        html: str | None,
        attributes: Mapping[str, object],
        fields: Sequence[FieldSpec],
        use_model: bool = False,
    ):
        providers = [AutoDiscoveryProvider()]
        reasoning_provider = self.model_router.provider(ModelRole.REASONING)
        if use_model and reasoning_provider is not None:
            providers.append(ReasoningCandidateProvider(reasoning_provider))
        engine = ExtractionEngine(tuple(providers))
        asset = RawAsset(
            asset_id=asset_id,
            source_url=source_url,
            text=text,
            html=html,
            attributes=dict(attributes),
        )
        return engine.extract(asset, fields)
