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

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ValueError("query must not be blank")
        if not self.collections:
            raise ValueError("at least one collection is required")
        if self.limit < 1 or self.limit > 100:
            raise ValueError("limit must be between 1 and 100")
        if not isinstance(self.mode, SearchMode):
            object.__setattr__(self, "mode", SearchMode(self.mode))
