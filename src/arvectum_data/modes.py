from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class ExecutionMode(StrEnum):
    FAST = "fast"
    STANDARD = "standard"
    DEEP = "deep"
    RESEARCH = "research"


@dataclass(frozen=True, slots=True)
class ModeProfile:
    mode: ExecutionMode
    endpoint: str
    baseline_stages: tuple[str, ...]
    optional_stages: tuple[str, ...]
    generative_model_required: bool
    network_discovery: bool
    max_query_expansions: int
    max_rerank_candidates: int
    max_discovery_sources: int
    max_evidence_items: int
    degradation: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["mode"] = self.mode.value
        payload["baseline_stages"] = list(self.baseline_stages)
        payload["optional_stages"] = list(self.optional_stages)
        return payload


MODE_PROFILES: dict[ExecutionMode, ModeProfile] = {
    ExecutionMode.FAST: ModeProfile(
        mode=ExecutionMode.FAST,
        endpoint="/v1/search",
        baseline_stages=("lexical-retrieval", "vector-retrieval", "fusion"),
        optional_stages=(),
        generative_model_required=False,
        network_discovery=False,
        max_query_expansions=0,
        max_rerank_candidates=0,
        max_discovery_sources=0,
        max_evidence_items=100,
        degradation="lexical-only remains available when embeddings are unavailable",
    ),
    ExecutionMode.STANDARD: ModeProfile(
        mode=ExecutionMode.STANDARD,
        endpoint="/v1/search",
        baseline_stages=("lexical-retrieval", "vector-retrieval", "fusion"),
        optional_stages=("rerank",),
        generative_model_required=False,
        network_discovery=False,
        max_query_expansions=0,
        max_rerank_candidates=20,
        max_discovery_sources=0,
        max_evidence_items=100,
        degradation="rerank fails open to deterministic hybrid ordering",
    ),
    ExecutionMode.DEEP: ModeProfile(
        mode=ExecutionMode.DEEP,
        endpoint="/v1/search",
        baseline_stages=("lexical-retrieval", "vector-retrieval", "fusion"),
        optional_stages=("query-expansion", "rerank"),
        generative_model_required=False,
        network_discovery=False,
        max_query_expansions=4,
        max_rerank_candidates=20,
        max_discovery_sources=0,
        max_evidence_items=100,
        degradation="optional expansion/rerank fail open to deterministic retrieval",
    ),
    ExecutionMode.RESEARCH: ModeProfile(
        mode=ExecutionMode.RESEARCH,
        endpoint="/v1/research",
        baseline_stages=(
            "discovery",
            "acquisition",
            "indexing",
            "retrieval",
            "grounded-synthesis",
        ),
        optional_stages=("query-expansion", "rerank"),
        generative_model_required=False,
        network_discovery=True,
        max_query_expansions=4,
        max_rerank_candidates=50,
        max_discovery_sources=25,
        max_evidence_items=50,
        degradation="reasoning failure returns evidence with explicit abstention",
    ),
}


def mode_profile(mode: ExecutionMode | str) -> ModeProfile:
    resolved = mode if isinstance(mode, ExecutionMode) else ExecutionMode(mode)
    return MODE_PROFILES[resolved]


def validate_search_envelope(
    execution_mode: ExecutionMode | str | None,
    *,
    expand_query: bool,
    query_expansion_limit: int,
    rerank: bool,
    rerank_candidates: int,
) -> ExecutionMode | None:
    if execution_mode is None:
        return None
    mode = (
        execution_mode
        if isinstance(execution_mode, ExecutionMode)
        else ExecutionMode(execution_mode)
    )
    if mode is ExecutionMode.RESEARCH:
        raise ValueError("research execution mode is only available on /v1/research")

    profile = mode_profile(mode)
    if expand_query and profile.max_query_expansions == 0:
        raise ValueError(f"{mode.value} execution mode does not allow query expansion")
    if expand_query and query_expansion_limit > profile.max_query_expansions:
        raise ValueError(
            f"{mode.value} execution mode allows at most "
            f"{profile.max_query_expansions} query expansions"
        )
    if rerank and profile.max_rerank_candidates == 0:
        raise ValueError(f"{mode.value} execution mode does not allow reranking")
    if rerank and rerank_candidates > profile.max_rerank_candidates:
        raise ValueError(
            f"{mode.value} execution mode allows at most "
            f"{profile.max_rerank_candidates} rerank candidates"
        )
    return mode


def validate_research_envelope(
    execution_mode: ExecutionMode | str | None,
    *,
    source_limit: int,
    evidence_limit: int,
) -> ExecutionMode | None:
    if execution_mode is None:
        return None
    mode = (
        execution_mode
        if isinstance(execution_mode, ExecutionMode)
        else ExecutionMode(execution_mode)
    )
    if mode is not ExecutionMode.RESEARCH:
        raise ValueError("only research execution mode is available on /v1/research")

    profile = mode_profile(mode)
    if source_limit > profile.max_discovery_sources:
        raise ValueError(
            f"research execution mode allows at most "
            f"{profile.max_discovery_sources} discovery sources"
        )
    if evidence_limit > profile.max_evidence_items:
        raise ValueError(
            f"research execution mode allows at most "
            f"{profile.max_evidence_items} evidence items"
        )
    return mode
