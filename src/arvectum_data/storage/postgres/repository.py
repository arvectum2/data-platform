from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...documents import DocumentIngestResult
from .models import (
    ChunkEmbeddingRow,
    ChunkRow,
    CollectionRow,
    DocumentRow,
    ProvenanceRow,
    ResourceRow,
)


@dataclass(frozen=True, slots=True)
class VectorSearchHit:
    chunk_id: str
    document_id: str
    resource_id: str
    canonical_uri: str
    text: str
    score: float


class DataRepository:
    def __init__(self, session: Session):
        self.session = session

    def ensure_collection(
        self,
        collection_id: str,
        *,
        owner: str,
        name: str,
        default_language: str = "simple",
        embedding_provider: str | None = None,
        embedding_model: str | None = None,
        embedding_dimension: int | None = None,
    ) -> CollectionRow:
        row = self.session.get(CollectionRow, collection_id)
        if row is None:
            row = CollectionRow(
                collection_id=collection_id,
                owner=owner,
                name=name,
                default_language=default_language,
                embedding_provider=embedding_provider,
                embedding_model=embedding_model,
                embedding_dimension=embedding_dimension,
            )
            self.session.add(row)
        else:
            row.owner = owner
            row.name = name
            row.default_language = default_language
            row.embedding_provider = embedding_provider
            row.embedding_model = embedding_model
            row.embedding_dimension = embedding_dimension
        self.session.flush()
        return row

    def persist_ingest(self, result: DocumentIngestResult) -> None:
        resource = self.session.get(ResourceRow, result.resource.resource_id)
        now = datetime.now(UTC)
        if resource is None:
            resource = ResourceRow(
                resource_id=result.resource.resource_id,
                collection_id=result.resource.collection_id,
                source_type=result.resource.source_type,
                canonical_uri=result.resource.canonical_uri,
                content_hash=result.resource.content_hash,
                first_seen_at=now,
                last_seen_at=now,
                metadata_json=dict(result.resource.metadata),
            )
            self.session.add(resource)
        else:
            resource.content_hash = result.resource.content_hash
            resource.last_seen_at = now
            resource.metadata_json = dict(result.resource.metadata)

        document = self.session.get(DocumentRow, result.document.document_id)
        if document is None:
            document = DocumentRow(
                document_id=result.document.document_id,
                resource_id=result.document.resource_id,
                title=result.document.title,
                text=result.document.text,
                media_type=result.document.media_type,
                content_hash=result.document.content_hash,
                extraction_status=result.document.extraction_status,
                metadata_json=dict(result.document.metadata),
            )
            self.session.add(document)

        for chunk in result.chunks:
            if self.session.get(ChunkRow, chunk.chunk_id) is None:
                self.session.add(
                    ChunkRow(
                        chunk_id=chunk.chunk_id,
                        document_id=chunk.document_id,
                        ordinal=chunk.ordinal,
                        text=chunk.text,
                        content_hash=chunk.content_hash,
                        char_start=chunk.char_start,
                        char_end=chunk.char_end,
                        token_estimate=chunk.token_estimate,
                        metadata_json=dict(chunk.metadata),
                    )
                )
                self.session.add(
                    ProvenanceRow(
                        resource_id=chunk.provenance.resource_id,
                        document_id=chunk.provenance.document_id,
                        chunk_id=chunk.chunk_id,
                        source_ref=chunk.provenance.canonical_uri,
                        metadata_json={"content_hash": chunk.provenance.content_hash},
                    )
                )
        self.session.flush()

    def upsert_embedding(
        self,
        *,
        chunk_id: str,
        provider: str,
        model: str,
        vector: Sequence[float],
    ) -> ChunkEmbeddingRow:
        existing = self.session.scalar(
            select(ChunkEmbeddingRow).where(
                ChunkEmbeddingRow.chunk_id == chunk_id,
                ChunkEmbeddingRow.provider == provider,
                ChunkEmbeddingRow.model == model,
            )
        )
        values = [float(value) for value in vector]
        if existing is None:
            existing = ChunkEmbeddingRow(
                chunk_id=chunk_id,
                provider=provider,
                model=model,
                dimension=len(values),
                vector=values,
            )
            self.session.add(existing)
        else:
            existing.dimension = len(values)
            existing.vector = values
        self.session.flush()
        return existing

    def search_vectors(
        self,
        query_vector: Sequence[float],
        *,
        collection_id: str,
        provider: str,
        model: str,
        limit: int = 10,
    ) -> list[VectorSearchHit]:
        if limit < 1:
            return []
        vector = [float(value) for value in query_vector]
        distance = ChunkEmbeddingRow.vector.cosine_distance(vector)
        statement = (
            select(
                ChunkRow.chunk_id,
                ChunkRow.document_id,
                ResourceRow.resource_id,
                ResourceRow.canonical_uri,
                ChunkRow.text,
                distance.label("distance"),
            )
            .join(ChunkEmbeddingRow, ChunkEmbeddingRow.chunk_id == ChunkRow.chunk_id)
            .join(DocumentRow, DocumentRow.document_id == ChunkRow.document_id)
            .join(ResourceRow, ResourceRow.resource_id == DocumentRow.resource_id)
            .where(
                ResourceRow.collection_id == collection_id,
                ChunkEmbeddingRow.provider == provider,
                ChunkEmbeddingRow.model == model,
                ChunkEmbeddingRow.dimension == len(vector),
            )
            .order_by(distance.asc(), ChunkRow.chunk_id.asc())
            .limit(limit)
        )
        rows = self.session.execute(statement).all()
        return [
            VectorSearchHit(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                resource_id=row.resource_id,
                canonical_uri=row.canonical_uri,
                text=row.text,
                score=1.0 - float(row.distance),
            )
            for row in rows
        ]
