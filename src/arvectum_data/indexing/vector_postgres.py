from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..storage.postgres import DataRepository
from .protocols import VectorSearchResult


class PostgresVectorIndex:
    """Collection/model scoped pgvector implementation of the VectorIndex contract."""

    def __init__(
        self,
        repository: DataRepository,
        *,
        collection_id: str,
        provider: str,
        model: str,
        dimension: int | None,
    ) -> None:
        if not collection_id:
            raise ValueError("collection_id must not be blank")
        if not provider:
            raise ValueError("provider must not be blank")
        if not model:
            raise ValueError("model must not be blank")
        if dimension is not None and dimension < 1:
            raise ValueError("dimension must be positive")
        self.repository = repository
        self.collection_id = collection_id
        self.provider = provider
        self.model = model
        self._dimension = dimension

    @property
    def dimension(self) -> int | None:
        return self._dimension

    def _values(self, vector: Sequence[float]) -> list[float]:
        values = [float(value) for value in vector]
        if not values:
            raise ValueError("embedding vector must not be empty")
        if self._dimension is None:
            self._dimension = len(values)
        elif len(values) != self._dimension:
            raise ValueError(
                f"Vector dimension mismatch: expected {self._dimension}, got {len(values)}"
            )
        return values

    def has_vector(self, vector_id: str) -> bool:
        return self.repository.embedding_exists(
            vector_id,
            collection_id=self.collection_id,
            provider=self.provider,
            model=self.model,
            dimension=self._dimension,
        )

    def upsert(
        self,
        vector_id: str,
        vector: Sequence[float],
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if metadata is not None:
            metadata_collection = metadata.get("collection_id")
            if metadata_collection is not None and str(metadata_collection) != self.collection_id:
                raise ValueError("vector metadata collection_id does not match index scope")
        if not self.repository.chunk_belongs_to_collection(vector_id, self.collection_id):
            raise ValueError(
                f"chunk {vector_id!r} does not belong to collection {self.collection_id!r}"
            )
        values = self._values(vector)
        self.repository.upsert_embedding(
            chunk_id=vector_id,
            provider=self.provider,
            model=self.model,
            vector=values,
        )

    def delete(self, vector_id: str) -> bool:
        return self.repository.delete_embedding(
            vector_id,
            collection_id=self.collection_id,
            provider=self.provider,
            model=self.model,
        )

    def search(
        self,
        query_vector: Sequence[float],
        *,
        limit: int = 10,
        allowed_vector_ids: set[str] | None = None,
        filters: Mapping[str, Sequence[str]] | None = None,
    ) -> list[VectorSearchResult]:
        values = self._values(query_vector)
        hits = self.repository.search_vectors(
            values,
            collection_id=self.collection_id,
            provider=self.provider,
            model=self.model,
            limit=limit,
            filters=filters,
            allowed_chunk_ids=allowed_vector_ids,
        )
        return [
            VectorSearchResult(
                vector_id=hit.chunk_id,
                score=hit.score,
                metadata={
                    "collection_id": self.collection_id,
                    "document_id": hit.document_id,
                    "resource_id": hit.resource_id,
                    "canonical_uri": hit.canonical_uri,
                    "title": hit.title,
                    "text": hit.text,
                },
            )
            for hit in hits
        ]
