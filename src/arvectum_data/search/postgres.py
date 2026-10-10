from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..indexing.vector_postgres import PostgresVectorIndex
from ..storage.postgres import DataRepository
from .models import BackendHit


class PostgresSearchBackend:
    def __init__(
        self,
        repository: DataRepository,
        *,
        collection_languages: Mapping[str, str] | None = None,
    ):
        self.repository = repository
        self.collection_languages = collection_languages

    def search_lexical(
        self,
        query: str,
        *,
        collections: Sequence[str],
        filters: Mapping[str, Sequence[str]] | None,
        limit: int,
    ) -> list[BackendHit]:
        if len(collections) > 1:
            return [
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
                for collection_id, hit in self.repository.search_lexical_collections(
                    query, collections=collections, limit=limit, filters=filters,
                    collection_languages=self.collection_languages,
                )
            ]
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
        if len(collections) > 1:
            return [
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
                for collection_id, hit in self.repository.search_vectors_collections(
                    query_vector,
                    collections=collections,
                    provider=provider,
                    model=model,
                    limit=limit,
                    filters=filters,
                )
            ]
        hits: list[BackendHit] = []
        per_collection_limit = max(limit, 1)
        for collection_id in collections:
            index = PostgresVectorIndex(
                self.repository,
                collection_id=collection_id,
                provider=provider,
                model=model,
                dimension=len(query_vector),
            )
            for hit in index.search(
                query_vector,
                limit=per_collection_limit,
                filters=filters,
            ):
                metadata = dict(hit.metadata)
                hits.append(
                    BackendHit(
                        chunk_id=hit.vector_id,
                        document_id=str(metadata["document_id"]),
                        resource_id=str(metadata["resource_id"]),
                        canonical_uri=str(metadata["canonical_uri"]),
                        title=str(metadata["title"]),
                        text=str(metadata["text"]),
                        score=hit.score,
                        metadata=metadata,
                    )
                )
        hits.sort(key=lambda item: (-item.score, item.chunk_id))
        return hits[:limit]
