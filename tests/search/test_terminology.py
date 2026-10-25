"""Cross-industry deterministic dictionary + technical source-fragment tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from arvectum_data.api.schemas import SearchRequest
from arvectum_data.indexing import HashingEmbeddingProvider
from arvectum_data.search import (
    BackendHit, HybridSearchEngine, SearchMode, SearchQuery,
    TerminologyGroup, expand_terminology, match_terminology,
)


def _pq():
    return TerminologyGroup(
        id="reactive-compensation",
        aliases=("СТАТКОМ", "STATCOM", "static synchronous compensator", "SVG"),
        contexts=("реактивная мощность", "подстанция", "ПС 220 кВ"),
        exclusions=("SVG vector graphics", "графические файлы SVG"),
        ambiguous_aliases=("SVG",),
    )


def _non_pq():
    return TerminologyGroup(
        id="medical-imaging",
        aliases=("МРТ", "магнитно-резонансная томография", "MRI"),
        contexts=("диагностика",),
    )


def test_lexicon_detects_buried_epc_equipment_and_preserves_exact_terms():
    g = _pq()
    r = match_terminology(
        "В рамках строительства подстанции выполнить поставку СТАТКОМ 8 МВАр.", (g,),
    )
    assert len(r) == 1
    assert r[0]["id"] == "reactive-compensation"
    assert "СТАТКОМ" in r[0]["terms"]
    assert r[0]["classification"] == "explicit_technical_candidate"


def test_ambiguous_alias_requires_context_and_negative_exclusions_override():
    g = _pq()
    assert match_terminology("Создание SVG vector graphics для баннеров", (g,)) == ()
    assert match_terminology("Создание SVG макетов для презентации", (g,)) == ()
    assert match_terminology("SVG для реактивная мощность, компенсация", (g,))
    assert match_terminology("Реконструкция подстанции без оборудования PQ", (g,)) == ()


def test_ontology_is_agnostic_to_industry():
    g = _non_pq()
    assert match_terminology("Поставка MRI для диагностика пациентов", (g,))
    assert match_terminology("Заказ на СТАТКОМ", (g,)) == ()


def test_terms_must_match_word_boundaries_not_prefixes():
    g = TerminologyGroup(id="test-term", aliases=("THD", "коэффициент искажений"))
    assert match_terminology("Проект THDisco площадки", (g,)) == ()
    assert match_terminology("Проект THD расчета гармоник", (g,))


def test_expansions_preserve_project_constraints_and_are_bounded():
    variants = expand_terminology("Модернизация ПС 220 кВ: СТАТКОМ", (_pq(),), limit=2)
    assert len(variants) == 2
    assert variants[0].text.startswith("Модернизация ПС 220 кВ:")
    assert variants[0].source.startswith("dictionary:")
    assert len({item.text.casefold() for item in variants}) == 2


@pytest.mark.parametrize("kwargs", [
    {"id": ".", "aliases": ("ok",)},
    {"id": "family-id", "aliases": ()},
    {"id": "family-id", "aliases": ("A",)},
    {"id": "family-id", "aliases": ("STATCOM",), "ambiguous_aliases": ("SVG",)},
    {"id": "family-id", "aliases": tuple(f"term-{i}" for i in range(21))},
])
def test_ontology_schema_fails_closed(kwargs):
    with pytest.raises(ValueError):
        TerminologyGroup(**kwargs)


def test_search_request_rejects_invalid_group_or_duplicate_ids():
    with pytest.raises(ValidationError):
        SearchRequest(query="сеть", collections=["a"], terminology_groups=[
            {"id": "x", "aliases": ["A"]},
        ])
    with pytest.raises(ValidationError):
        SearchRequest(query="сеть", collections=["a"], terminology_groups=[
            {"id": "group", "aliases": ["STATCOM"]},
            {"id": "group", "aliases": ["УКРМ"]},
        ])


class Lexical:
    def __init__(self):
        self.queries = []

    def search_lexical(self, query, *, collections, filters, limit):
        self.queries.append((query, collections))
        return [BackendHit(
            chunk_id="epc-chunk-01", document_id="epc-doc-01",
            resource_id="epc-res-01",
            canonical_uri="https://source.example.net/epc/equipment",
            title="Модернизация подстанции",
            text="Раздел электрооборудование: монтаж STATCOM в составе EPC",
            score=0.9, metadata={"original_sha256": "abc"},
        )]


class Vector:
    def search_vector(self, *args, **kwargs):
        return []


def test_engine_expands_without_llm_and_annotates_source_chunk():
    lexical = Lexical()
    eng = HybridSearchEngine(
        lexical_backend=lexical,
        vector_backend=Vector(),
        embedding_provider=HashingEmbeddingProvider(dimension=16),
        query_expander=None,
    )
    req = SearchQuery(
        query="Модернизация ПС 220 кВ: СТАТКОМ",
        collections=("eis-223",), mode=SearchMode.LEXICAL,
        terminology_groups=(_pq(),), terminology_expansion_limit=2,
        expand_query=False,
        terminology_version="power-quality-ontology/0.1",
    )
    result = eng.search(req)
    assert len(lexical.queries) == 3
    assert all(x[1] == ("eis-223",) for x in lexical.queries)
    assert result[0].document_id == "epc-doc-01"
    assert result[0].metadata["original_sha256"] == "abc"
    assert result[0].metadata["terminology_version"] == "power-quality-ontology/0.1"
    matches = result[0].metadata["terminology_matches"]
    assert len(matches) == 1 and matches[0]["id"] == "reactive-compensation"
    assert matches[0]["terms"] == ["STATCOM"]
    assert len(eng.last_expansions) == 2
    assert any(x.stage == "terminology-expansion" for x in eng.last_diagnostics)


def test_engine_without_ontology_has_identical_default_behavior():
    lexical = Lexical()
    eng = HybridSearchEngine(
        lexical_backend=lexical,
        vector_backend=Vector(), embedding_provider=HashingEmbeddingProvider(16),
    )
    r = eng.search(SearchQuery(query="СТАТКОМ", collections=("one",), mode=SearchMode.LEXICAL))
    assert len(lexical.queries) == 1
    assert "terminology_matches" not in r[0].metadata



def test_fast_and_standard_execution_modes_deny_extra_terminology_budget():
    for mode in ("fast", "standard"):
        with pytest.raises(ValueError, match="terminology expansion"):
            SearchQuery(
                query="СТАТКОМ", collections=("one",),
                mode=SearchMode.LEXICAL,
                execution_mode=mode,
                terminology_groups=(_pq(),),
            )
    deep = SearchQuery(
        query="СТАТКОМ", collections=("one",), mode=SearchMode.LEXICAL,
        execution_mode="deep", terminology_groups=(_pq(),),
        terminology_expansion_limit=4,
    )
    assert deep.terminology_expansion_limit == 4


def test_manual_and_domain_variants_share_eight_variant_budget():
    lexical = Lexical()
    eng = HybridSearchEngine(
        lexical_backend=lexical, vector_backend=Vector(),
        embedding_provider=HashingEmbeddingProvider(16),
    )
    req = SearchQuery(
        query="СТАТКОМ", collections=("one",), mode=SearchMode.LEXICAL,
        query_variants=tuple("custom"+str(i) for i in range(7)),
        terminology_groups=(_pq(),), terminology_expansion_limit=8,
    )
    eng.search(req)
    assert len(lexical.queries) == 9  # original + seven manual + one domain
    assert len(eng.last_expansions) == 1
