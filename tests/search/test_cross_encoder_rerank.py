from __future__ import annotations

from arvectum_data.indexing import HashingEmbeddingProvider
from arvectum_data.search import (
    BackendHit,
    CrossEncoderReranker,
    HybridSearchEngine,
    SearchQuery,
)


def _hit(chunk_id: str, score: float) -> BackendHit:
    return BackendHit(
        chunk_id=chunk_id,
        document_id=f"d-{chunk_id}",
        resource_id=f"r-{chunk_id}",
        canonical_uri=f"https://example.com/{chunk_id}",
        title=chunk_id,
        text=f"candidate text {chunk_id}",
        score=score,
    )


class Lexical:
    def search_lexical(self, query, *, collections, filters, limit):
        return [_hit("a", 9.0), _hit("b", 8.0), _hit("c", 7.0)]


class Vector:
    def search_vector(self, query_vector, *, collections, filters, provider, model, limit):
        return [_hit("a", 0.9), _hit("b", 0.8), _hit("c", 0.7)]


class FakeCrossEncoder:
    provider_name = "fake-cross-encoder"
    model_name = "tiny-reranker-v1"

    def __init__(self, scores):
        self.scores = scores
        self.pairs = None

    def score_pairs(self, pairs):
        self.pairs = list(pairs)
        return self.scores


def _engine(scorer):
    return HybridSearchEngine(
        lexical_backend=Lexical(),
        vector_backend=Vector(),
        embedding_provider=HashingEmbeddingProvider(dimension=16),
        reranker=CrossEncoderReranker(scorer, max_candidates=2),
    )


def test_cross_encoder_reranks_bounded_candidates() -> None:
    scorer = FakeCrossEncoder([0.2, 0.9])
    engine = _engine(scorer)

    hits = engine.search(
        SearchQuery(
            query="best candidate",
            collections=("one",),
            limit=2,
            rerank=True,
            rerank_candidates=2,
        )
    )

    assert [hit.chunk_id for hit in hits] == ["b", "a"]
    assert hits[0].scores.rerank == 0.9
    assert len(scorer.pairs) == 2
    assert scorer.pairs[0][0] == "best candidate"
    assert all("candidate text c" not in pair[1] for pair in scorer.pairs)


def test_cross_encoder_score_count_mismatch_fails_open() -> None:
    hits = _engine(FakeCrossEncoder([0.5])).search(
        SearchQuery(
            query="best candidate",
            collections=("one",),
            limit=2,
            rerank=True,
            rerank_candidates=2,
        )
    )

    assert [hit.chunk_id for hit in hits] == ["a", "b"]
    assert all(hit.scores.rerank is None for hit in hits)


def test_cross_encoder_diagnostics_expose_provider_identity() -> None:
    engine = _engine(FakeCrossEncoder([0.2, 0.9]))
    engine.search(
        SearchQuery(
            query="best candidate",
            collections=("one",),
            limit=2,
            rerank=True,
            rerank_candidates=2,
        )
    )

    diagnostic = next(item for item in engine.last_diagnostics if item.stage == "rerank")
    assert diagnostic.status == "executed"
    assert diagnostic.provider == "fake-cross-encoder"
    assert diagnostic.model == "tiny-reranker-v1"
