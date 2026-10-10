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


class VariantAwareLexical:
    def search_lexical(self, query, *, collections, filters, limit):
        if query == "original":
            return [_hit("original-best", 1.0)]
        if query == "expanded":
            return [_hit("expanded-best", 5.0)]
        return []


class VariantAwareEmbedding:
    provider_name = "variant-test"
    model_name = "variant-test"
    dimension = 1

    def embed_query(self, text):
        return [1.0 if text == "original" else 2.0]

    def embed_texts(self, texts):
        return [[1.0] for _ in texts]


class VariantAwareVector:
    def search_vector(self, query_vector, *, collections, filters, provider, model, limit):
        if query_vector == [1.0]:
            return [_hit("original-best", 0.9)]
        return [_hit("expanded-best", 0.95)]


def test_query_variants_contribute_bounded_rrf_signal() -> None:
    engine = HybridSearchEngine(
        lexical_backend=VariantAwareLexical(),
        vector_backend=VariantAwareVector(),
        embedding_provider=VariantAwareEmbedding(),
    )

    without_variant = engine.search(
        SearchQuery(
            query="original",
            collections=("one",),
            mode=SearchMode.HYBRID,
        )
    )
    with_variant = engine.search(
        SearchQuery(
            query="original",
            collections=("one",),
            mode=SearchMode.HYBRID,
            query_variants=("expanded",),
            query_variant_weight=0.5,
        )
    )

    assert without_variant[0].chunk_id == "original-best"
    assert {hit.chunk_id for hit in with_variant[:2]} == {
        "original-best",
        "expanded-best",
    }
    assert with_variant[0].chunk_id == "original-best"
    assert with_variant[1].scores.lexical == 5.0
    assert with_variant[1].scores.vector == 0.95


def test_query_variants_are_deduplicated_and_bounded() -> None:
    import pytest

    query = SearchQuery(
        query="original",
        collections=("one",),
        query_variants=(" original ", "expanded", "expanded", "   "),
    )
    assert query.query_variants == ("expanded",)

    with pytest.raises(ValueError, match="at most 8 query variants"):
        SearchQuery(
            query="original",
            collections=("one",),
            query_variants=tuple(f"variant-{index}" for index in range(9)),
        )

def test_hybrid_search_exposes_safe_stage_diagnostics() -> None:
    engine = HybridSearchEngine(
        lexical_backend=FakeLexical(),
        vector_backend=FakeVector(),
        embedding_provider=HashingEmbeddingProvider(dimension=16),
    )

    engine.search(
        SearchQuery(
            query="secret query text",
            collections=("one",),
            mode=SearchMode.HYBRID,
        )
    )

    by_stage = {item.stage: item for item in engine.last_diagnostics}
    assert {
        "lexical-retrieval",
        "embedding-query",
        "vector-retrieval",
        "fusion",
        "total-search",
    }.issubset(by_stage)
    assert by_stage["embedding-query"].provider == "hashing"
    assert by_stage["embedding-query"].model == "local-hash-v1"
    assert all(item.duration_ms >= 0 for item in engine.last_diagnostics)
    serialized = repr(engine.last_diagnostics)
    assert "secret query text" not in serialized


def test_unavailable_optional_search_stages_are_visible_as_skipped() -> None:
    engine = HybridSearchEngine(
        lexical_backend=FakeLexical(),
        vector_backend=FakeVector(),
        embedding_provider=HashingEmbeddingProvider(dimension=16),
    )

    engine.search(
        SearchQuery(
            query="cable",
            collections=("one",),
            mode=SearchMode.HYBRID,
            expand_query=True,
            rerank=True,
            rerank_candidates=20,
        )
    )

    by_stage = {item.stage: item for item in engine.last_diagnostics}
    assert by_stage["query-expansion"].status == "skipped-unavailable"
    assert by_stage["rerank"].status == "skipped-unavailable"


class _UnboundedQueryExpander:
    name = "unbounded-test"

    def expand(self, query, *, limit):
        # A buggy provider returns duplicate/case-fold variants beyond the
        # requested bound; the search engine enforces the contract itself.
        from arvectum_data.search import QueryExpansion

        return (
            QueryExpansion(" Original ", "test"),
            QueryExpansion("EXPANDED", "test"),
            QueryExpansion("expanded", "test"),
            QueryExpansion(" ", "test"),
            QueryExpansion("next", "test"),
            QueryExpansion("fourth", "test"),
        )


def test_expander_is_deduplicated_and_bounded_before_backend_or_embedding_calls() -> None:
    seen: list[str] = []

    class RecordingLexical:
        def search_lexical(self, query, *, collections, filters, limit):
            seen.append(query)
            return [_hit(query.strip(), 1.0)]

    engine = HybridSearchEngine(
        lexical_backend=RecordingLexical(),
        vector_backend=FakeVector(),
        embedding_provider=HashingEmbeddingProvider(dimension=16),
        query_expander=_UnboundedQueryExpander(),
    )
    hits = engine.search(
        SearchQuery(
            query="original",
            collections=("one",),
            mode=SearchMode.LEXICAL,
            expand_query=True,
            query_expansion_limit=2,
        )
    )
    assert seen == ["original", "EXPANDED", "next"]
    assert [item.text for item in engine.last_expansions] == ["EXPANDED", "next"]
    assert len(hits) == 3
    diagnostics = {item.stage: item for item in engine.last_diagnostics}
    assert diagnostics["query-expansion"].metadata["variants"] == 2
    assert diagnostics["lexical-retrieval"].metadata["calls"] == 3


def test_explicit_query_variants_dedupe_case_insensitively() -> None:
    query = SearchQuery(
        query="Original", collections=("one",),
        query_variants=(" original ", "Expanded", "expanded"),
    )
    assert query.query_variants == ("Expanded",)


def test_failed_query_expansion_isolated_from_lexical_retrieval():
    class BrokenExpander:
        provider_name = "isolated-test"
        model_name = "no-network"

        def expand(self, query, *, limit):
            raise RuntimeError("sensitive content must not enter diagnostics")

    engine = HybridSearchEngine(
        lexical_backend=FakeLexical(),
        vector_backend=FakeVector(),
        embedding_provider=HashingEmbeddingProvider(dimension=16),
        query_expander=BrokenExpander(),
    )
    hits = engine.search(SearchQuery(
        query="private procurement terms", collections=("one",),
        mode=SearchMode.LEXICAL, expand_query=True,
    ))
    assert hits
    assert engine.last_expansions == ()
    diagnostics = {item.stage: item for item in engine.last_diagnostics}
    assert diagnostics["query-expansion"].status == "failed-open"
    assert diagnostics["query-expansion"].metadata["variants"] == 0
    assert diagnostics["lexical-retrieval"].metadata["calls"] == 1
    assert diagnostics["total-search"].metadata["query_count"] == 1
    assert "sensitive content" not in repr(engine.last_diagnostics)
    assert "private procurement" not in repr(engine.last_diagnostics)
