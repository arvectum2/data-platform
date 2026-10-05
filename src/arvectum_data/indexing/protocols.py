from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class VectorSearchResult:
    vector_id: str
    score: float
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class VectorIndex(Protocol):
    """Storage-level vector index contract shared by local and production backends."""

    @property
    def dimension(self) -> int | None: ...

    def has_vector(self, vector_id: str) -> bool: ...

    def upsert(
        self,
        vector_id: str,
        vector: Sequence[float],
        metadata: Mapping[str, Any] | None = None,
    ) -> None: ...

    def delete(self, vector_id: str) -> bool: ...

    def search(
        self,
        query_vector: Sequence[float],
        *,
        limit: int = 10,
        allowed_vector_ids: set[str] | None = None,
        filters: Mapping[str, Sequence[str]] | None = None,
    ) -> list[VectorSearchResult]: ...
