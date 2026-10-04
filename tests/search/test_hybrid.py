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
