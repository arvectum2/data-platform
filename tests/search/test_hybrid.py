from arvectum_data.indexing import HashingEmbeddingProvider
from arvectum_data.search import BackendHit, HybridSearchEngine, SearchMode, SearchQuery


def _hit(chunk_id: str, score: float) -> BackendHit:
    return BackendHit(
        chunk_id=chunk_id,
        document_id=f"d-{chunk_id}",
        resource_id=f"r-{chunk_id}",
        canonical_uri=f"https://example.com/{chunk_id}",
        title=chunk_id,
        text=f"text {chunk_id}",
        score=score,
    )


class FakeLexical:
    def search_lexical(self, query, *, collections, filters, limit):
        return [_hit("lex-only", 9.0), _hit("both", 8.0)]


class FakeVector:
    def search_vector(self, query_vector, *, collections, filters, provider, model, limit):
        return [_hit("both", 0.95), _hit("vec-only", 0.90)]


def test_hybrid_rrf_rewards_hits_present_in_both_lists() -> None:
    engine = HybridSearchEngine(
        lexical_backend=FakeLexical(),
        vector_backend=FakeVector(),
        embedding_provider=HashingEmbeddingProvider(dimension=16),
    )

    hits = engine.search(
        SearchQuery(query="cable", collections=("one",), mode=SearchMode.HYBRID)
    )

    assert hits[0].chunk_id == "both"
    assert hits[0].scores.lexical == 8.0
    assert hits[0].scores.vector == 0.95
    assert hits[0].evidence[0].canonical_uri.endswith("/both")


def test_lexical_mode_does_not_call_vector_backend() -> None:
    class ExplodingVector:
        def search_vector(self, *args, **kwargs):
            raise AssertionError("vector backend should not be called")

    engine = HybridSearchEngine(
        lexical_backend=FakeLexical(),
        vector_backend=ExplodingVector(),
        embedding_provider=HashingEmbeddingProvider(dimension=16),
    )

    hits = engine.search(
        SearchQuery(query="cable", collections=("one",), mode=SearchMode.LEXICAL)
    )

    assert hits
    assert all(hit.scores.vector is None for hit in hits)


def test_product_ranker_hook_runs_after_generic_fusion() -> None:
    seen: list[str] = []

    def ranker(request, hits):
        seen.extend(hit.chunk_id for hit in hits)
        return sorted(hits, key=lambda hit: hit.chunk_id, reverse=True)

    engine = HybridSearchEngine(
        lexical_backend=FakeLexical(),
        vector_backend=FakeVector(),
        embedding_provider=HashingEmbeddingProvider(dimension=16),
        product_ranker=ranker,
    )

    hits = engine.search(
        SearchQuery(query="cable", collections=("one",), mode=SearchMode.HYBRID)
    )

    assert set(seen) == {"both", "lex-only", "vec-only"}
    assert [hit.chunk_id for hit in hits] == ["vec-only", "lex-only", "both"]


class SingletonLexical:
    def search_lexical(self, query, *, collections, filters, limit):
        return [_hit("weak-both", 0.001)]


class DeepVector:
    def search_vector(self, query_vector, *, collections, filters, provider, model, limit):
        hits = [_hit("semantic-best", 0.95)]
        hits.extend(_hit(f"filler-{index}", 0.90 - index / 1000) for index in range(1, 24))
        hits.append(_hit("weak-both", 0.30))
        return hits


def test_weighted_rrf_can_prefer_semantic_top_hit_without_changing_defaults() -> None:
    engine = HybridSearchEngine(
        lexical_backend=SingletonLexical(),
        vector_backend=DeepVector(),
        embedding_provider=HashingEmbeddingProvider(dimension=16),
    )

    equal = engine.search(
        SearchQuery(
            query="responsibility",
            collections=("one",),
            mode=SearchMode.HYBRID,
            limit=10,
        )
    )
    semantic_first = engine.search(
        SearchQuery(
            query="responsibility",
            collections=("one",),
            mode=SearchMode.HYBRID,
            limit=10,
            lexical_weight=1.0,
            vector_weight=4.0,
        )
    )

    assert equal[0].chunk_id == "weak-both"
    assert semantic_first[0].chunk_id == "semantic-best"
    assert semantic_first[0].scores.fusion > semantic_first[1].scores.fusion


def test_hybrid_rejects_zero_zero_fusion_weights() -> None:
    import pytest

    with pytest.raises(ValueError, match="at least one positive"):
        SearchQuery(
            query="cable",
            collections=("one",),
            mode=SearchMode.HYBRID,
            lexical_weight=0.0,
            vector_weight=0.0,
        )
