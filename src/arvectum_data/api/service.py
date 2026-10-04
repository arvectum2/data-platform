from __future__ import annotations

import hashlib
import os
import tempfile
import time
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from ..acquisition import AcquisitionEngine
from ..acquisition.security import UnsafeURL, validate_public_url
from ..documents import ingest_file, ingest_url
from ..connectors import (
    ConnectorRegistry,
    DuckDuckGoHTMLConnector,
    ManualURLConnector,
    SitemapConnector,
)
from ..engine import AutoDiscoveryProvider, ExtractionEngine, FieldSpec, RawAsset
from ..orchestration import URLExtractionPipeline
from ..indexing import (
    BaseEmbeddingProvider,
    EmbeddingConfig,
    EmbeddingServerUnavailableError,
    build_embedding_provider,
)
from ..search import HybridSearchEngine, PostgresSearchBackend, SearchHit, SearchQuery
from ..storage.postgres import (
    ChunkEmbeddingRow,
    ChunkRow,
    CollectionRow,
    DataRepository,
    DocumentRow,
    PipelineRunRow,
    ResourceRow,
    RelevanceFeedbackRow,
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
    ) -> None:
        self.settings = settings
        self.acquisition = acquisition
        self.connector_registry = connector_registry or self._default_connector_registry()
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

    @staticmethod
    def _default_connector_registry() -> ConnectorRegistry:
        registry = ConnectorRegistry()
        registry.register(ManualURLConnector())
        registry.register(SitemapConnector())
        registry.register(DuckDuckGoHTMLConnector())
        return registry

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
    ):
        connector = self.connector_registry.get(connector_name)
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
            "database_configured": self.session_factory is not None,
            "embedding_provider": self.embedding_provider.provider_name,
            "embedding_model": self.embedding_provider.model_name,
            "embedding_dimension": self.embedding_provider.dimension,
            "metrics": metrics,
        }

    def create_collection(
        self,
        *,
        collection_id: str,
        owner: str,
        name: str,
        default_language: str,
        access_policy: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        with self._require_factory()() as session:
            repo = DataRepository(session)
            row = repo.ensure_collection(
                collection_id,
                owner=owner,
                name=name,
                default_language=default_language,
                embedding_provider=self.embedding_provider.provider_name,
                embedding_model=self.embedding_provider.model_name,
                embedding_dimension=self.embedding_provider.dimension,
                access_policy=None if access_policy is None else dict(access_policy),
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

    def _validate_embedding_contract(self, collection: CollectionRow) -> None:
        expected = (
            collection.embedding_provider,
            collection.embedding_model,
            collection.embedding_dimension,
        )
        actual = (
            self.embedding_provider.provider_name,
            self.embedding_provider.model_name,
            self.embedding_provider.dimension,
        )
        if expected != actual:
            raise EmbeddingContractMismatch(
                f"collection {collection.collection_id!r} embedding contract "
                f"{expected!r} does not match runtime {actual!r}"
            )

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

    def search(
        self,
        request: SearchQuery,
        *,
        consumer: str | None = None,
    ) -> list[SearchHit]:
        with self._require_factory()() as session:
            for collection_id in request.collections:
                collection = session.get(CollectionRow, collection_id)
                if collection is None:
                    raise CollectionNotFound(collection_id)
                allowed_consumers = tuple(
                    str(item)
                    for item in (collection.access_policy or {}).get(
                        "allowed_consumers", []
                    )
                    if str(item)
                )
                if allowed_consumers and consumer not in allowed_consumers:
                    raise CollectionAccessDenied(collection_id)
                self._validate_embedding_contract(collection)

            backend = PostgresSearchBackend(DataRepository(session))
            engine = HybridSearchEngine(
                lexical_backend=backend,
                vector_backend=backend,
                embedding_provider=self.embedding_provider,
            )
            return engine.search(request)



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
            self._validate_embedding_contract(collection)
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
                self._validate_embedding_contract(collection)
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
                run.status = "completed"
                run.metrics_json = {
                    "chunks_seen": len(chunks),
                    "embeddings_written": len(vectors),
                    "embedding_attempts": embedding_attempts,
                    "skipped_unchanged": False,
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
    ):
        if not self.settings.allow_private_fetches:
            validate_public_url(url)
        pipeline = URLExtractionPipeline(acquisition=self.acquisition)
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
    ):
        engine = ExtractionEngine((AutoDiscoveryProvider(),))
        asset = RawAsset(
            asset_id=asset_id,
            source_url=source_url,
            text=text,
            html=html,
            attributes=dict(attributes),
        )
        return engine.extract(asset, fields)
