from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Mapping, Sequence

from sqlalchemy import case, func, select
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
    title: str
    text: str
    score: float


@dataclass(frozen=True, slots=True)
class LexicalSearchHit:
    chunk_id: str
    document_id: str
    resource_id: str
    canonical_uri: str
    title: str
    text: str
    score: float


def _language_config(value: str | None) -> str:
    normalized = (value or "simple").strip().lower()
    if normalized in {"ru", "rus", "russian"}:
        return "russian"
    if normalized in {"en", "eng", "english"}:
        return "english"
    return "simple"


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
        access_policy: dict[str, object] | None = None,
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
                access_policy=dict(access_policy or {}),
            )
            self.session.add(row)
        else:
            row.owner = owner
            row.name = name
            row.default_language = default_language
            row.embedding_provider = embedding_provider
            row.embedding_model = embedding_model
            row.embedding_dimension = embedding_dimension
            if access_policy is not None:
                row.access_policy = dict(access_policy)
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
        self.session.flush()

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
        self.session.flush()

        new_chunks = []
        provenance_rows = []
        for chunk in result.chunks:
            if self.session.get(ChunkRow, chunk.chunk_id) is not None:
                continue
            new_chunks.append(
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
            provenance_rows.append(
                ProvenanceRow(
                    resource_id=chunk.provenance.resource_id,
                    document_id=chunk.provenance.document_id,
                    chunk_id=chunk.chunk_id,
                    source_ref=chunk.provenance.canonical_uri,
                    metadata_json={"content_hash": chunk.provenance.content_hash},
                )
            )

        if new_chunks:
            self.session.add_all(new_chunks)
            self.session.flush()
            self.session.add_all(provenance_rows)
        self.session.flush()

    def existing_embedding_chunk_ids(
        self,
        chunk_ids: Sequence[str],
        *,
        provider: str,
        model: str,
    ) -> set[str]:
        ids = [str(chunk_id) for chunk_id in chunk_ids if str(chunk_id)]
        if not ids:
            return set()
        return set(
            self.session.scalars(
                select(ChunkEmbeddingRow.chunk_id).where(
                    ChunkEmbeddingRow.chunk_id.in_(ids),
                    ChunkEmbeddingRow.provider == provider,
                    ChunkEmbeddingRow.model == model,
                )
            )
        )

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
        if not values:
            raise ValueError("embedding vector must not be empty")
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

    def _filter_conditions(
        self,
        filters: Mapping[str, Sequence[str]] | None,
    ) -> list:
        conditions = []
        for key, raw_values in (filters or {}).items():
            values = [str(value) for value in raw_values if str(value)]
            if not values:
                continue
            if key == "source_type":
                conditions.append(ResourceRow.source_type.in_(values))
            elif key == "media_type":
                conditions.append(DocumentRow.media_type.in_(values))
            elif key == "resource_id":
                conditions.append(ResourceRow.resource_id.in_(values))
            elif key == "canonical_uri":
                conditions.append(ResourceRow.canonical_uri.in_(values))
            else:
                raise ValueError(f"Unsupported search filter: {key}")
        return conditions

    def search_vectors(
        self,
        query_vector: Sequence[float],
        *,
        collection_id: str,
        provider: str,
        model: str,
        limit: int = 10,
        filters: Mapping[str, Sequence[str]] | None = None,
    ) -> list[VectorSearchHit]:
        if limit < 1:
            return []
        vector = [float(value) for value in query_vector]
        if not vector:
            return []
        distance = ChunkEmbeddingRow.vector.cosine_distance(vector)
        statement = (
            select(
                ChunkRow.chunk_id,
                ChunkRow.document_id,
                ResourceRow.resource_id,
                ResourceRow.canonical_uri,
                DocumentRow.title,
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
                *self._filter_conditions(filters),
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
                title=row.title,
                text=row.text,
                score=1.0 - float(row.distance),
            )
            for row in rows
        ]

    def search_lexical(
        self,
        query: str,
        *,
        collection_id: str,
        limit: int = 10,
        language: str | None = None,
        filters: Mapping[str, Sequence[str]] | None = None,
    ) -> list[LexicalSearchHit]:
        normalized_query = query.strip()
        if not normalized_query or limit < 1:
            return []

        collection = self.session.get(CollectionRow, collection_id)
        config = _language_config(language or (collection.default_language if collection else None))
        vector_column = {
            "russian": ChunkRow.search_vector_russian,
            "english": ChunkRow.search_vector_english,
            "simple": ChunkRow.search_vector_simple,
        }[config]
        tsquery = func.websearch_to_tsquery(config, normalized_query)
        rank = func.ts_rank_cd(vector_column, tsquery)
        exact_boost = case(
            (
                func.strpos(func.lower(ChunkRow.text), normalized_query.lower()) > 0,
                0.25,
            ),
            else_=0.0,
        )
        score = rank + exact_boost
        statement = (
            select(
                ChunkRow.chunk_id,
                ChunkRow.document_id,
                ResourceRow.resource_id,
                ResourceRow.canonical_uri,
                DocumentRow.title,
                ChunkRow.text,
                score.label("score"),
            )
            .join(DocumentRow, DocumentRow.document_id == ChunkRow.document_id)
            .join(ResourceRow, ResourceRow.resource_id == DocumentRow.resource_id)
            .where(
                ResourceRow.collection_id == collection_id,
                vector_column.op("@@")(tsquery),
                *self._filter_conditions(filters),
            )
            .order_by(score.desc(), ChunkRow.chunk_id.asc())
            .limit(limit)
        )
        rows = self.session.execute(statement).all()
        return [
            LexicalSearchHit(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                resource_id=row.resource_id,
                canonical_uri=row.canonical_uri,
                title=row.title,
                text=row.text,
                score=float(row.score),
            )
            for row in rows
        ]
