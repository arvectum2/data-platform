from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class ConnectorState(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class DiscoveredResource:
    canonical_uri: str
    provider: str
    source_type: str = "url"
    external_id: str | None = None
    title: str | None = None
    snippet: str | None = None
    rank: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DiscoveryPage:
    resources: tuple[DiscoveredResource, ...]
    next_cursor: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConnectorHealth:
    name: str
    state: ConnectorState
    capabilities: tuple[str, ...]
    detail: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConnectorPolicy:
    max_attempts: int = 3
    base_delay_s: float = 0.25
    max_delay_s: float = 2.0
    min_interval_s: float = 0.10

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if self.base_delay_s < 0 or self.max_delay_s < 0 or self.min_interval_s < 0:
            raise ValueError("connector delays must be non-negative")
        if self.max_delay_s < self.base_delay_s:
            raise ValueError("max_delay_s must be >= base_delay_s")

    def delay_after(self, attempt: int) -> float:
        if attempt < 1:
            return 0.0
        return min(self.max_delay_s, self.base_delay_s * (2 ** (attempt - 1)))
