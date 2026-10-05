from __future__ import annotations

import json

from arvectum_data.indexing import HashingEmbeddingProvider
from arvectum_data.models import ModelDescriptor, ModelLocality, ModelResponse, ModelRole
from arvectum_data.search import (
    BackendHit,
    DictionaryQueryExpander,
    HybridSearchEngine,
    QueryExpansion,
    ReasoningQueryExpander,
    SearchMode,
    SearchQuery,
)


def _hit(chunk_id: str, score: float) -> BackendHit:
    return BackendHit(
        chunk_id=chunk_id,
        document_id=f"d-{chunk_id}",
        resource_id=f"r-{chunk_id}",
        canonical_uri=f"https://example.com/{chunk_id}",
        title=chunk_id,
        text=chunk_id,
        score=score,
    )


class Lexical:
    def __init__(self):
        self.queries = []

    def search_lexical(self, query, *, collections, filters, limit):
        self.queries.append(query)
        return [_hit(query, 1.0)]


class Vector:
    def search_vector(self, query_vector, *, collections, filters, provider, model, limit):
        return []


class StaticExpander:
    name = "static"

    def expand(self, query, *, limit):
        return (
            QueryExpansion("expanded one", "dictionary:test", 0.5),
            QueryExpansion("expanded two", "reasoning", 0.4),
        )[:limit]


def test_query_expansion_is_opt_in_bounded_and_explainable():
    lexical = Lexical()
    engine = HybridSearchEngine(
        lexical_backend=lexical,
        vector_backend=Vector(),
        embedding_provider=HashingEmbeddingProvider(dimension=16),
        query_expander=StaticExpander(),
    )
    request = SearchQuery(
        query="original",
        collections=("one",),
        mode=SearchMode.LEXICAL,
        expand_query=True,
        query_expansion_limit=1,
    )

    engine.search(request)

    assert lexical.queries == ["original", "expanded one"]
    assert engine.last_expansions == (
        QueryExpansion("expanded one", "dictionary:test", 0.5),
    )


def test_expander_failure_falls_back_to_original_query():
    class Broken:
        name = "broken"

        def expand(self, query, *, limit):
            raise RuntimeError("offline")

    lexical = Lexical()
    engine = HybridSearchEngine(
        lexical_backend=lexical,
        vector_backend=Vector(),
        embedding_provider=HashingEmbeddingProvider(dimension=16),
        query_expander=Broken(),
    )

    engine.search(
        SearchQuery(
            query="original",
            collections=("one",),
            mode=SearchMode.LEXICAL,
            expand_query=True,
        )
    )

    assert lexical.queries == ["original"]
    assert engine.last_expansions == ()


def test_dictionary_expander_uses_domain_equivalents_without_hidden_retrieval():
    expander = DictionaryQueryExpander(
        {"нмцк": ("начальная максимальная цена контракта",)}
    )
    result = expander.expand("обоснование НМЦК", limit=4)

    assert result[0].text == "обоснование начальная максимальная цена контракта"
    assert result[0].source == "dictionary:нмцк"


class FakeProvider:
    descriptor = ModelDescriptor(
        ModelRole.REASONING,
        "fake",
        "qe",
        "1",
        ModelLocality.LOCAL,
        ("text-generation", "reasoning"),
    )

    def generate(self, request):
        return ModelResponse(
            json.dumps(["contract price rationale", "contract price rationale", ""]),
            "fake",
            "qe",
            "1",
            ModelLocality.LOCAL,
            1.0,
        )


def test_reasoning_expander_deduplicates_and_limits_variants():
    result = ReasoningQueryExpander(FakeProvider()).expand(
        "price rationale",
        limit=2,
    )

    assert [item.text for item in result] == ["contract price rationale"]
    assert result[0].source == "reasoning"
