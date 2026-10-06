from __future__ import annotations

import pytest

from arvectum_data.modes import (
    ExecutionMode,
    mode_profile,
    validate_research_envelope,
    validate_search_envelope,
)


def test_mode_profiles_are_product_neutral_and_bounded() -> None:
    fast = mode_profile(ExecutionMode.FAST)
    standard = mode_profile(ExecutionMode.STANDARD)
    deep = mode_profile(ExecutionMode.DEEP)
    research = mode_profile(ExecutionMode.RESEARCH)

    assert fast.generative_model_required is False
    assert fast.max_query_expansions == 0
    assert fast.max_rerank_candidates == 0

    assert standard.optional_stages == ("rerank",)
    assert standard.max_rerank_candidates == 20
    assert standard.max_query_expansions == 0

    assert deep.optional_stages == ("query-expansion", "rerank")
    assert deep.max_query_expansions == 4
    assert deep.max_rerank_candidates == 20

    assert research.endpoint == "/v1/research"
    assert research.max_discovery_sources == 25
    assert research.max_evidence_items == 50
    assert research.max_rerank_candidates == 50


def test_search_mode_envelopes_reject_out_of_depth_overrides() -> None:
    with pytest.raises(ValueError, match="does not allow reranking"):
        validate_search_envelope(
            "fast",
            expand_query=False,
            query_expansion_limit=4,
            rerank=True,
            rerank_candidates=10,
        )

    with pytest.raises(ValueError, match="does not allow query expansion"):
        validate_search_envelope(
            "standard",
            expand_query=True,
            query_expansion_limit=3,
            rerank=False,
            rerank_candidates=20,
        )

    with pytest.raises(ValueError, match="at most 20 rerank candidates"):
        validate_search_envelope(
            "deep",
            expand_query=False,
            query_expansion_limit=4,
            rerank=True,
            rerank_candidates=21,
        )

    assert (
        validate_search_envelope(
            "deep",
            expand_query=True,
            query_expansion_limit=4,
            rerank=True,
            rerank_candidates=20,
        )
        is ExecutionMode.DEEP
    )


def test_research_mode_is_route_scoped() -> None:
    with pytest.raises(ValueError, match="only available on /v1/research"):
        validate_search_envelope(
            "research",
            expand_query=False,
            query_expansion_limit=4,
            rerank=False,
            rerank_candidates=20,
        )

    assert (
        validate_research_envelope(
            "research",
            source_limit=25,
            evidence_limit=50,
        )
        is ExecutionMode.RESEARCH
    )

    with pytest.raises(ValueError, match="only research execution mode"):
        validate_research_envelope(
            "deep",
            source_limit=8,
            evidence_limit=8,
        )
