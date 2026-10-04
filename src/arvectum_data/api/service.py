from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from ..acquisition import AcquisitionEngine
from ..acquisition.security import UnsafeURL, validate_public_url
from ..documents import ingest_file, ingest_url
from ..engine import AutoDiscoveryProvider, ExtractionEngine, FieldSpec, RawAsset
from ..orchestration import URLExtractionPipeline
from ..indexing import (
    BaseEmbeddingProvider,
    EmbeddingConfig,
    build_embedding_provider,
)
from ..search import HybridSearchEngine, PostgresSearchBackend, SearchHit, SearchQuery
from ..storage.postgres import (
    ChunkRow,
    CollectionRow,
    DataRepository,
    DocumentRow,
    PipelineRunRow,
    ResourceRow,
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
    }


class DataPlatformService:
    def __init__(
        self,
        settings: Settings,
        *,
        session_factory: sessionmaker[Session] | None = None,
        embedding_provider: BaseEmbeddingProvider | None = None,
        acquisition: AcquisitionEngine | None = None,
    ) -> None:
        self.settings = settings
        self.acquisition = acquisition
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

    def _require_factory(self) -> sessionmaker[Session]:
        if self.session_factory is None:
            raise PlatformNotConfigured("ARVECTUM_DATA_DATABASE_URL is not configured")
        return self.session_factory

    def status(self) -> dict[str, Any]:
        database_ok = False
        if self.session_factory is not None:
            try:
                with self.session_factory() as session:
                    session.execute(text("SELECT 1"))
                database_ok = True
            except Exception:
                database_ok = False
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
        }

    def create_collection(
        self,
        *,
        collection_id: str,
        owner: str,
        name: str,
        default_language: str,
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

    def ingest_document_bytes(
        self,
        *,
        collection_id: str,
        filename: str,
        content: bytes,
        title: str | None = None,
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
                canonical_uri=f"upload://{filename}",
                title=title or filename,
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

    def _persist_and_index(self, result) -> dict[str, Any]:
        with self._require_factory()() as session:
            collection = session.get(CollectionRow, result.resource.collection_id)
            if collection is None:
                raise CollectionNotFound(result.resource.collection_id)
            self._validate_embedding_contract(collection)

            repo = DataRepository(session)
            repo.persist_ingest(result)
            vectors = self.embedding_provider.embed_texts(
                [chunk.text for chunk in result.chunks]
            )
            if len(vectors) != len(result.chunks):
                raise RuntimeError("embedding provider returned unexpected vector count")
            for chunk, vector in zip(result.chunks, vectors):
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
                "embeddings": len(vectors),
                "canonical_uri": result.resource.canonical_uri,
                "extraction_status": result.document.extraction_status,
            }

    def search(self, request: SearchQuery) -> list[SearchHit]:
        with self._require_factory()() as session:
            for collection_id in request.collections:
                collection = session.get(CollectionRow, collection_id)
                if collection is None:
                    raise CollectionNotFound(collection_id)
                self._validate_embedding_contract(collection)

            backend = PostgresSearchBackend(DataRepository(session))
            engine = HybridSearchEngine(
                lexical_backend=backend,
                vector_backend=backend,
                embedding_provider=self.embedding_provider,
            )
            return engine.search(request)



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
        revision = str(uuid.uuid4())

        with factory() as session:
            collection = session.get(CollectionRow, collection_id)
            if collection is None:
                raise CollectionNotFound(collection_id)
            self._validate_embedding_contract(collection)
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
                vectors = self.embedding_provider.embed_texts(
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

                run = session.get(PipelineRunRow, run_id)
                if run is None:
                    raise RuntimeError("reindex run disappeared")
                run.status = "completed"
                run.metrics_json = {
                    "chunks_seen": len(chunks),
                    "embeddings_written": len(vectors),
                }
                run.completed_at = datetime.now(UTC)
                collection.active_index_revision = revision
                session.commit()
                return self._job_payload(run)
        except Exception as exc:
            with factory() as session:
                run = session.get(PipelineRunRow, run_id)
                if run is not None:
                    run.status = "failed"
                    run.metrics_json = {"error_type": type(exc).__name__}
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
