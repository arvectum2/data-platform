from __future__ import annotations

import json

from arvectum_data.indexing import HashingEmbeddingProvider
from arvectum_data.models import ModelDescriptor, ModelLocality, ModelResponse, ModelRole
from arvectum_data.search import BackendHit, HybridSearchEngine, ReasoningReranker, SearchQuery


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


class FakeProvider:
    descriptor = ModelDescriptor(
        ModelRole.REASONING,
        "fake",
        "reranker",
        "1",
        ModelLocality.LOCAL,
        ("text-generation", "reasoning"),
    )

    def __init__(self, payload):
        self.payload = payload
        self.request = None

    def generate(self, request):
        self.request = request
        return ModelResponse(
            json.dumps(self.payload),
            "fake",
            "reranker",
            "1",
            ModelLocality.LOCAL,
            1.0,
        )


def _engine(provider):
    return HybridSearchEngine(
        lexical_backend=Lexical(),
        vector_backend=Vector(),
        embedding_provider=HashingEmbeddingProvider(dimension=16),
        reranker=ReasoningReranker(provider, max_candidates=2),
    )


def test_reranker_reorders_bounded_candidates_and_preserves_fusion_scores():
    provider = FakeProvider([
        {"chunk_id": "b", "score": 0.99},
        {"chunk_id": "a", "score": 0.25},
    ])
    engine = _engine(provider)

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
    assert hits[0].scores.rerank == 0.99
    assert hits[0].scores.fusion < hits[1].scores.fusion
    assert provider.request.metadata["candidate_count"] == 2
    assert '"chunk_id": "c"' not in provider.request.prompt


def test_reranker_rejects_unknown_ids_without_injecting_documents():
    provider = FakeProvider([
        {"chunk_id": "invented", "score": 1.0},
        {"chunk_id": "b", "score": 0.9},
    ])
    hits = _engine(provider).search(
        SearchQuery(
            query="best candidate",
            collections=("one",),
            limit=2,
            rerank=True,
            rerank_candidates=2,
        )
    )

    assert [hit.chunk_id for hit in hits] == ["b", "a"]
    assert all(hit.chunk_id != "invented" for hit in hits)


def test_reranker_failure_falls_back_to_original_order():
    class BrokenProvider(FakeProvider):
        def generate(self, request):
            raise RuntimeError("offline")

    engine = _engine(BrokenProvider([]))
    hits = engine.search(
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


def test_rerank_is_disabled_by_default():
    provider = FakeProvider([{"chunk_id": "b", "score": 1.0}])
    hits = _engine(provider).search(
        SearchQuery(query="best candidate", collections=("one",), limit=2)
    )

    assert [hit.chunk_id for hit in hits] == ["a", "b"]
    assert provider.request is None
