from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable, Iterable

from ..indexing import BaseEmbeddingProvider
from .models import (
    BackendHit,
    SearchEvidence,
    SearchHit,
    SearchMode,
    SearchQuery,
    SearchScores,
)
from .protocols import LexicalBackend, VectorBackend


@dataclass
class _AccumulatedHit:
    hit: BackendHit
    lexical_score: float | None = None
    vector_score: float | None = None
    fusion_score: float = 0.0


class HybridSearchEngine:
    def __init__(
        self,
        *,
        lexical_backend: LexicalBackend,
        vector_backend: VectorBackend,
        embedding_provider: BaseEmbeddingProvider,
        rrf_k: int = 60,
        candidate_multiplier: int = 3,
        product_ranker: Callable[[SearchQuery, list[SearchHit]], list[SearchHit]] | None = None,
    ) -> None:
        if rrf_k < 1:
            raise ValueError("rrf_k must be positive")
        if candidate_multiplier < 1:
            raise ValueError("candidate_multiplier must be positive")
        self.lexical_backend = lexical_backend
        self.vector_backend = vector_backend
        self.embedding_provider = embedding_provider
        self.rrf_k = rrf_k
        self.candidate_multiplier = candidate_multiplier
        self.product_ranker = product_ranker

    def search(self, request: SearchQuery) -> list[SearchHit]:
        candidate_limit = min(300, max(20, request.limit * self.candidate_multiplier))
        lexical_hits: list[BackendHit] = []
        vector_hits: list[BackendHit] = []

        if request.mode in {SearchMode.LEXICAL, SearchMode.HYBRID}:
            lexical_hits = self.lexical_backend.search_lexical(
                request.query,
                collections=request.collections,
                filters=request.filters,
                limit=candidate_limit,
            )

        if request.mode in {SearchMode.VECTOR, SearchMode.HYBRID}:
            query_vector = self.embedding_provider.embed_query(request.query)
            vector_hits = self.vector_backend.search_vector(
                query_vector,
                collections=request.collections,
                filters=request.filters,
                provider=self.embedding_provider.provider_name,
                model=self.embedding_provider.model_name,
                limit=candidate_limit,
            )

        accumulated: dict[str, _AccumulatedHit] = {}
        self._accumulate(accumulated, lexical_hits, kind="lexical")
        self._accumulate(accumulated, vector_hits, kind="vector")

        ranked = sorted(
            accumulated.values(),
            key=lambda item: (-item.fusion_score, item.hit.chunk_id),
        )
        results = [self._to_search_hit(item) for item in ranked]
        if self.product_ranker is not None:
            results = self.product_ranker(request, results)
        return results[: request.limit]

    def _accumulate(
        self,
        accumulated: dict[str, _AccumulatedHit],
        hits: Iterable[BackendHit],
        *,
        kind: str,
    ) -> None:
        for rank, hit in enumerate(hits, start=1):
            item = accumulated.setdefault(hit.chunk_id, _AccumulatedHit(hit=hit))
            item.fusion_score += 1.0 / (self.rrf_k + rank)
            if kind == "lexical":
                item.lexical_score = hit.score
            else:
                item.vector_score = hit.score

    @staticmethod
    def _to_search_hit(item: _AccumulatedHit) -> SearchHit:
        hit = item.hit
        preview = " ".join(hit.text.split())[:280]
        return SearchHit(
            chunk_id=hit.chunk_id,
            document_id=hit.document_id,
            resource_id=hit.resource_id,
            canonical_uri=hit.canonical_uri,
            title=hit.title,
            preview=preview,
            text=hit.text,
            scores=SearchScores(
                lexical=item.lexical_score,
                vector=item.vector_score,
                fusion=item.fusion_score,
            ),
            evidence=(
                SearchEvidence(
                    resource_id=hit.resource_id,
                    document_id=hit.document_id,
                    chunk_id=hit.chunk_id,
                    canonical_uri=hit.canonical_uri,
                ),
            ),
            metadata=hit.metadata,
        )
