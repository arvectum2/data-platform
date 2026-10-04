from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..storage.postgres import DataRepository
from .models import BackendHit


class PostgresSearchBackend:
    def __init__(self, repository: DataRepository):
        self.repository = repository

    def search_lexical(
        self,
        query: str,
        *,
        collections: Sequence[str],
        filters: Mapping[str, Sequence[str]] | None,
        limit: int,
    ) -> list[BackendHit]:
        hits: list[BackendHit] = []
        per_collection_limit = max(limit, 1)
        for collection_id in collections:
            for hit in self.repository.search_lexical(
                query,
                collection_id=collection_id,
                limit=per_collection_limit,
                filters=filters,
            ):
                hits.append(
                    BackendHit(
                        chunk_id=hit.chunk_id,
                        document_id=hit.document_id,
                        resource_id=hit.resource_id,
                        canonical_uri=hit.canonical_uri,
                        title=hit.title,
                        text=hit.text,
                        score=hit.score,
                        metadata={"collection_id": collection_id},
                    )
                )
        hits.sort(key=lambda item: (-item.score, item.chunk_id))
        return hits[:limit]

    def search_vector(
        self,
        query_vector: Sequence[float],
        *,
        collections: Sequence[str],
        filters: Mapping[str, Sequence[str]] | None,
        provider: str,
        model: str,
        limit: int,
    ) -> list[BackendHit]:
        hits: list[BackendHit] = []
        per_collection_limit = max(limit, 1)
        for collection_id in collections:
            for hit in self.repository.search_vectors(
                query_vector,
                collection_id=collection_id,
                provider=provider,
                model=model,
                limit=per_collection_limit,
                filters=filters,
            ):
                hits.append(
                    BackendHit(
                        chunk_id=hit.chunk_id,
                        document_id=hit.document_id,
                        resource_id=hit.resource_id,
                        canonical_uri=hit.canonical_uri,
                        title=hit.title,
                        text=hit.text,
                        score=hit.score,
                        metadata={"collection_id": collection_id},
                    )
                )
        hits.sort(key=lambda item: (-item.score, item.chunk_id))
        return hits[:limit]
