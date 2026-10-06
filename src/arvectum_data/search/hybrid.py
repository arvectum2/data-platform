from __future__ import annotations

from dataclasses import dataclass
import time
from collections.abc import Callable, Iterable

from ..indexing import BaseEmbeddingProvider
from .expansion import QueryExpander
from .models import (
    BackendHit,
    SearchEvidence,
    SearchHit,
    SearchMode,
    SearchQuery,
    SearchScores,
    SearchStageDiagnostic,
)
from .protocols import LexicalBackend, VectorBackend
from .rerank import Reranker


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
        reranker: Reranker | None = None,
        query_expander: QueryExpander | None = None,
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
        self.reranker = reranker
        self.query_expander = query_expander
        self.last_expansions = ()
        self.last_diagnostics: tuple[SearchStageDiagnostic, ...] = ()

    def search(self, request: SearchQuery) -> list[SearchHit]:
        total_started = time.perf_counter()
        diagnostics: list[SearchStageDiagnostic] = []
        target_limit = request.rerank_candidates if request.rerank else request.limit
        candidate_limit = min(300, max(20, target_limit * self.candidate_multiplier))
        accumulated: dict[str, _AccumulatedHit] = {}

        queries = [(request.query, 1.0)]
        queries.extend(
            (variant, request.query_variant_weight)
            for variant in request.query_variants
        )
        self.last_expansions = ()
        if request.expand_query:
            expansion_started = time.perf_counter()
            expansion_status = "skipped-unavailable"
            expansion_provider, expansion_model = self._component_identity(
                self.query_expander
            )
            expansions = ()
            if self.query_expander is not None:
                try:
                    expansions = self.query_expander.expand(
                        request.query,
                        limit=request.query_expansion_limit,
                    )
                    expansion_status = "executed"
                except Exception:
                    expansions = ()
                    expansion_status = "failed-open"
            explicit = {
                request.query.casefold(),
                *(item.casefold() for item in request.query_variants),
            }
            expansions = tuple(
                item for item in expansions if item.text.casefold() not in explicit
            )
            self.last_expansions = expansions
            queries.extend((item.text, item.weight) for item in expansions)
            diagnostics.append(
                SearchStageDiagnostic(
                    stage="query-expansion",
                    status=expansion_status,
                    duration_ms=round(
                        (time.perf_counter() - expansion_started) * 1000,
                        3,
                    ),
                    provider=expansion_provider,
                    model=expansion_model,
                    metadata={"variants": len(expansions)},
                )
            )

        lexical_ms = 0.0
        vector_ms = 0.0
        embedding_ms = 0.0
        lexical_calls = 0
        vector_calls = 0

        for query_text, query_weight in queries:
            if request.mode in {SearchMode.LEXICAL, SearchMode.HYBRID}:
                started = time.perf_counter()
                lexical_hits = self.lexical_backend.search_lexical(
                    query_text,
                    collections=request.collections,
                    filters=request.filters,
                    limit=candidate_limit,
                )
                lexical_ms += (time.perf_counter() - started) * 1000
                lexical_calls += 1
                self._accumulate(
                    accumulated,
                    lexical_hits,
                    kind="lexical",
                    weight=request.lexical_weight * query_weight,
                )

            if request.mode in {SearchMode.VECTOR, SearchMode.HYBRID}:
                started = time.perf_counter()
                query_vector = self.embedding_provider.embed_query(query_text)
                embedding_ms += (time.perf_counter() - started) * 1000

                started = time.perf_counter()
                vector_hits = self.vector_backend.search_vector(
                    query_vector,
                    collections=request.collections,
                    filters=request.filters,
                    provider=self.embedding_provider.provider_name,
                    model=self.embedding_provider.model_name,
                    limit=candidate_limit,
                )
                vector_ms += (time.perf_counter() - started) * 1000
                vector_calls += 1
                self._accumulate(
                    accumulated,
                    vector_hits,
                    kind="vector",
                    weight=request.vector_weight * query_weight,
                )

        if request.mode in {SearchMode.LEXICAL, SearchMode.HYBRID}:
            diagnostics.append(
                SearchStageDiagnostic(
                    stage="lexical-retrieval",
                    status="executed",
                    duration_ms=round(lexical_ms, 3),
                    provider=type(self.lexical_backend).__name__,
                    metadata={
                        "calls": lexical_calls,
                        "candidate_limit": candidate_limit,
                    },
                )
            )
        if request.mode in {SearchMode.VECTOR, SearchMode.HYBRID}:
            diagnostics.extend(
                (
                    SearchStageDiagnostic(
                        stage="embedding-query",
                        status="executed",
                        duration_ms=round(embedding_ms, 3),
                        provider=self.embedding_provider.provider_name,
                        model=self.embedding_provider.model_name,
                        metadata={"calls": vector_calls},
                    ),
                    SearchStageDiagnostic(
                        stage="vector-retrieval",
                        status="executed",
                        duration_ms=round(vector_ms, 3),
                        provider=type(self.vector_backend).__name__,
                        metadata={
                            "calls": vector_calls,
                            "candidate_limit": candidate_limit,
                        },
                    ),
                )
            )

        fusion_started = time.perf_counter()
        ranked = sorted(
            accumulated.values(),
            key=lambda item: (-item.fusion_score, item.hit.chunk_id),
        )
        results = [self._to_search_hit(item) for item in ranked]
        diagnostics.append(
            SearchStageDiagnostic(
                stage="fusion",
                status="executed",
                duration_ms=round(
                    (time.perf_counter() - fusion_started) * 1000,
                    3,
                ),
                metadata={"candidates": len(results)},
            )
        )

        if self.product_ranker is not None:
            started = time.perf_counter()
            results = self.product_ranker(request, results)
            diagnostics.append(
                SearchStageDiagnostic(
                    stage="product-ranker",
                    status="executed",
                    duration_ms=round(
                        (time.perf_counter() - started) * 1000,
                        3,
                    ),
                    provider=getattr(
                        self.product_ranker,
                        "__name__",
                        type(self.product_ranker).__name__,
                    ),
                )
            )

        if request.rerank:
            started = time.perf_counter()
            rerank_provider, rerank_model = self._component_identity(self.reranker)
            if self.reranker is None:
                rerank_status = "skipped-unavailable"
            else:
                results, rerank_status = self._rerank(
                    request,
                    results[: request.rerank_candidates],
                )
            diagnostics.append(
                SearchStageDiagnostic(
                    stage="rerank",
                    status=rerank_status,
                    duration_ms=round((time.perf_counter() - started) * 1000, 3),
                    provider=rerank_provider,
                    model=rerank_model,
                    metadata={
                        "candidate_count": min(
                            len(results),
                            request.rerank_candidates,
                        )
                    },
                )
            )

        final_results = results[: request.limit]
        diagnostics.append(
            SearchStageDiagnostic(
                stage="total-search",
                status="executed",
                duration_ms=round((time.perf_counter() - total_started) * 1000, 3),
                metadata={
                    "query_count": len(queries),
                    "returned_hits": len(final_results),
                },
            )
        )
        self.last_diagnostics = tuple(diagnostics)
        return final_results

    def _rerank(
        self,
        request: SearchQuery,
        hits: list[SearchHit],
    ) -> tuple[list[SearchHit], str]:
        try:
            reranked = (
                self.reranker.rerank(request, hits)
                if self.reranker is not None
                else ()
            )
        except Exception:
            return hits, "failed-open"
        if not reranked:
            return hits, "failed-open"

        score_by_id = {item.chunk_id: item.score for item in reranked}
        rank_by_id = {item.chunk_id: item.rank for item in reranked}
        original_rank = {hit.chunk_id: index for index, hit in enumerate(hits)}
        enriched = [
            SearchHit(
                chunk_id=hit.chunk_id,
                document_id=hit.document_id,
                resource_id=hit.resource_id,
                canonical_uri=hit.canonical_uri,
                title=hit.title,
                preview=hit.preview,
                text=hit.text,
                scores=SearchScores(
                    lexical=hit.scores.lexical,
                    vector=hit.scores.vector,
                    fusion=hit.scores.fusion,
                    rerank=score_by_id.get(hit.chunk_id),
                ),
                evidence=hit.evidence,
                metadata=hit.metadata,
            )
            for hit in hits
        ]
        return (
            sorted(
                enriched,
                key=lambda hit: (
                    rank_by_id.get(
                        hit.chunk_id,
                        len(hits) + original_rank[hit.chunk_id],
                    ),
                    original_rank[hit.chunk_id],
                ),
            ),
            "executed",
        )

    @staticmethod
    def _component_identity(component) -> tuple[str | None, str | None]:
        if component is None:
            return None, None
        provider = getattr(component, "provider", None)
        descriptor = getattr(provider, "descriptor", None)
        if descriptor is not None:
            return str(descriptor.provider), str(descriptor.model)
        provider_name = getattr(component, "name", None)
        if provider_name is not None:
            return str(provider_name), None
        return type(component).__name__, None

    def _accumulate(
        self,
        accumulated: dict[str, _AccumulatedHit],
        hits: Iterable[BackendHit],
        *,
        kind: str,
        weight: float,
    ) -> None:
        for rank, hit in enumerate(hits, start=1):
            item = accumulated.setdefault(hit.chunk_id, _AccumulatedHit(hit=hit))
            item.fusion_score += weight / (self.rrf_k + rank)
            if kind == "lexical":
                item.lexical_score = max(
                    item.lexical_score if item.lexical_score is not None else hit.score,
                    hit.score,
                )
            else:
                item.vector_score = max(
                    item.vector_score if item.vector_score is not None else hit.score,
                    hit.score,
                )

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
