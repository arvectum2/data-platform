from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from ...acquisition.security import validate_public_url
from ...documents import ingest_bytes, ingest_url
from ...processing import ChunkingConfig
from ...models import ModelRole

from ...storage.postgres import (
    ChunkEmbeddingRow,
    ChunkRow,
    CollectionRow,
    DataRepository,
    DataRecordRow,
    DocumentRow,
    PipelineRunRow,
    ProvenanceRow,
    ResourceRow,
)

from ..service_support import (
    CollectionNotFound,
    EmbeddingContractMismatch,
    _collection_payload,
)


class CollectionServiceMixin:
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
                retention_policy=(None if retention_policy is None else dict(retention_policy)),
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
            key: int(counts[key]) for key in ("resources", "documents", "chunks", "embeddings")
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
            chunk_ids = select(ChunkRow.chunk_id).where(ChunkRow.document_id.in_(document_ids))

            resources = (
                session.scalar(
                    select(func.count())
                    .select_from(ResourceRow)
                    .where(ResourceRow.collection_id == collection_id)
                )
                or 0
            )
            documents = (
                session.scalar(
                    select(func.count())
                    .select_from(DocumentRow)
                    .where(DocumentRow.resource_id.in_(resource_ids))
                )
                or 0
            )
            chunks = (
                session.scalar(
                    select(func.count())
                    .select_from(ChunkRow)
                    .where(ChunkRow.document_id.in_(document_ids))
                )
                or 0
            )
            embeddings = (
                session.scalar(
                    select(func.count())
                    .select_from(ChunkEmbeddingRow)
                    .where(ChunkEmbeddingRow.chunk_id.in_(chunk_ids))
                )
                or 0
            )
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
                "active_index_revision": (collection.active_index_revision if collection else None),
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
        result = ingest_bytes(
            content,
            filename=filename,
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
        processing_metadata = dict(result.document.metadata or {})
        return {
            "collection_id": result.resource.collection_id,
            "resource_id": result.resource.resource_id,
            "document_id": result.document.document_id,
            "canonical_uri": result.resource.canonical_uri,
            "title": result.document.title,
            "media_type": result.document.media_type,
            "extraction_status": result.document.extraction_status,
            "metadata": processing_metadata,
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
        result = ingest_bytes(
            content,
            filename=filename,
            collection_id=collection_id,
            canonical_uri=canonical_uri or f"upload://{filename}",
            title=title or filename,
            pre_chunked=pre_chunked,
            ocr_provider=self.ocr_provider,
            vision_provider=self.model_router.provider(ModelRole.VISION),
        )
        return self._persist_and_index(result)

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
