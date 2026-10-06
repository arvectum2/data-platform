from __future__ import annotations

from arvectum_data.indexing import HashingEmbeddingProvider
from arvectum_data.search import (
    BackendHit,
    CrossEncoderReranker,
    HttpCrossEncoderScorer,
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

def test_search_query_accepts_cross_encoder_strategy() -> None:
    from arvectum_data.search import RerankStrategy

    request = SearchQuery(
        query="best candidate",
        collections=("one",),
        limit=2,
        rerank=True,
        rerank_candidates=3,
        rerank_strategy="cross_encoder",
    )
    assert request.rerank_strategy is RerankStrategy.CROSS_ENCODER


def test_search_query_prefers_cross_encoder_strategy_by_default() -> None:
    from arvectum_data.search import RerankStrategy

    request = SearchQuery(
        query="best candidate",
        collections=("one",),
        rerank=True,
        rerank_candidates=3,
    )
    assert request.rerank_strategy is RerankStrategy.CROSS_ENCODER


def test_http_cross_encoder_scorer_posts_payload(monkeypatch) -> None:
    import json

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"scores": [0.1, 0.9]}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    scorer = HttpCrossEncoderScorer(
        base_url="http://127.0.0.1:8091",
        model_name="BAAI/bge-reranker-v2-m3",
        timeout_seconds=0.8,
    )

    scores = scorer.score_pairs((("q1", "p1"), ("q2", "p2")))

    assert scores == (0.1, 0.9)
    assert captured["url"] == "http://127.0.0.1:8091/score"
    assert captured["timeout"] == 0.8
    assert captured["payload"] == {
        "model": "BAAI/bge-reranker-v2-m3",
        "pairs": [["q1", "p1"], ["q2", "p2"]],
    }


def test_http_cross_encoder_failure_still_fails_open(monkeypatch) -> None:
    def unavailable(request, timeout):
        raise OSError("sidecar offline")

    monkeypatch.setattr("urllib.request.urlopen", unavailable)
    scorer = HttpCrossEncoderScorer(
        base_url="http://127.0.0.1:8091",
        model_name="BAAI/bge-reranker-v2-m3",
        timeout_seconds=0.1,
    )
    hits = _engine(scorer).search(
        SearchQuery(
            query="best candidate",
            collections=("one",),
            limit=2,
            rerank=True,
            rerank_candidates=2,
        )
    )

    assert [hit.chunk_id for hit in hits] == ["a", "b"]
    diagnostic = next(item for item in _engine(scorer).last_diagnostics if False)
