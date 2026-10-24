from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re
from typing import Any, Mapping

from ..modes import ExecutionMode, mode_profile, validate_search_envelope
from .terminology import TerminologyGroup


class SearchMode(StrEnum):
    LEXICAL = "lexical"
    VECTOR = "vector"
    HYBRID = "hybrid"


class RerankStrategy(StrEnum):
    REASONING = "reasoning"
    CROSS_ENCODER = "cross_encoder"


@dataclass(frozen=True, slots=True)
class BackendHit:
    chunk_id: str
    document_id: str
    resource_id: str
    canonical_uri: str
    title: str
    text: str
    score: float
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SearchEvidence:
    resource_id: str
    document_id: str
    chunk_id: str
    canonical_uri: str


@dataclass(frozen=True, slots=True)
class SearchScores:
    lexical: float | None
    vector: float | None
    fusion: float
    rerank: float | None = None


@dataclass(frozen=True, slots=True)
class SearchStageDiagnostic:
    stage: str
    status: str
    duration_ms: float
    provider: str | None = None
    model: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SearchHit:
    chunk_id: str
    document_id: str
    resource_id: str
    canonical_uri: str
    title: str
    preview: str
    text: str
    scores: SearchScores
    evidence: tuple[SearchEvidence, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SearchQuery:
    query: str
    collections: tuple[str, ...]
    filters: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    limit: int = 10
    mode: SearchMode = SearchMode.HYBRID
    lexical_weight: float = 1.0
    vector_weight: float = 1.0
    query_variants: tuple[str, ...] = ()
    query_variant_weight: float = 0.5
    terminology_groups: tuple[TerminologyGroup, ...] = ()
    terminology_expansion_limit: int = 5
    terminology_version: str | None = None
    expand_query: bool = False
    query_expansion_limit: int = 4
    collapse_by_canonical_uri: bool = False
    rerank: bool = False
    rerank_candidates: int = 20
    rerank_strategy: RerankStrategy = RerankStrategy.CROSS_ENCODER
    execution_mode: ExecutionMode | None = None

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ValueError("query must not be blank")
        if not self.collections:
            raise ValueError("at least one collection is required")
        if self.limit < 1 or self.limit > 100:
            raise ValueError("limit must be between 1 and 100")
        if not isinstance(self.mode, SearchMode):
            object.__setattr__(self, "mode", SearchMode(self.mode))
        if self.lexical_weight < 0 or self.vector_weight < 0:
            raise ValueError("search fusion weights must be non-negative")
        if self.mode is SearchMode.HYBRID and self.lexical_weight == 0 and self.vector_weight == 0:
            raise ValueError("hybrid search requires at least one positive fusion weight")
        if self.query_variant_weight < 0 or self.query_variant_weight > 1:
            raise ValueError("query_variant_weight must be between 0 and 1")
        if not 1 <= self.terminology_expansion_limit <= 8:
            raise ValueError("terminology expansion limit must be 1..8")
        if self.terminology_version is not None and (
            not isinstance(self.terminology_version, str)
            or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._/-]{1,127}", self.terminology_version)
        ):
            raise ValueError("terminology version must be a safe version label")
        if len(self.terminology_groups) > 12 or any(
            not isinstance(group, TerminologyGroup) for group in self.terminology_groups
        ):
            raise ValueError("at most 12 valid terminology groups are allowed")
        ids = [group.id for group in self.terminology_groups]
        if len(ids) != len(set(ids)):
            raise ValueError("terminology group IDs must be unique")
        if self.query_expansion_limit < 1 or self.query_expansion_limit > 8:
            raise ValueError("query_expansion_limit must be between 1 and 8")
        if self.rerank_candidates < 1 or self.rerank_candidates > 100:
            raise ValueError("rerank_candidates must be between 1 and 100")
        if not isinstance(self.rerank_strategy, RerankStrategy):
            object.__setattr__(self, "rerank_strategy", RerankStrategy(self.rerank_strategy))
        if self.rerank and self.rerank_candidates < self.limit:
            raise ValueError("rerank_candidates must be greater than or equal to limit")
        resolved_execution_mode = validate_search_envelope(
            self.execution_mode,
            expand_query=self.expand_query,
            query_expansion_limit=self.query_expansion_limit,
            rerank=self.rerank,
            rerank_candidates=self.rerank_candidates,
        )
        if resolved_execution_mode is not None and self.terminology_groups:
            max_expansions = mode_profile(resolved_execution_mode).max_query_expansions
            if max_expansions == 0 or self.terminology_expansion_limit > max_expansions:
                raise ValueError(
                    f"{resolved_execution_mode.value} execution mode does not allow "
                    "this terminology expansion depth"
                )
        object.__setattr__(self, "execution_mode", resolved_execution_mode)
        normalized_variants: list[str] = []
        seen = {self.query.strip().casefold()}
        for variant in self.query_variants:
            cleaned = variant.strip()
            key = cleaned.casefold()
            if not cleaned or key in seen:
                continue
            seen.add(key)
            normalized_variants.append(cleaned)
        if len(normalized_variants) > 8:
            raise ValueError("at most 8 query variants are allowed")
        object.__setattr__(self, "query_variants", tuple(normalized_variants))
