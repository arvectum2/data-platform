from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class SearchMode(StrEnum):
    LEXICAL = "lexical"
    VECTOR = "vector"
    HYBRID = "hybrid"


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
    collapse_by_canonical_uri: bool = False
    rerank: bool = False
    rerank_candidates: int = 20

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
        if self.rerank_candidates < 1 or self.rerank_candidates > 100:
            raise ValueError("rerank_candidates must be between 1 and 100")
        if self.rerank and self.rerank_candidates < self.limit:
            raise ValueError("rerank_candidates must be greater than or equal to limit")
        normalized_variants: list[str] = []
        seen = {self.query.strip()}
        for variant in self.query_variants:
            cleaned = variant.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            normalized_variants.append(cleaned)
        if len(normalized_variants) > 8:
            raise ValueError("at most 8 query variants are allowed")
        object.__setattr__(self, "query_variants", tuple(normalized_variants))
