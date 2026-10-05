from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Mapping


@dataclass(frozen=True, slots=True)
class RefreshPolicy:
    interval_seconds: int = 86400
    missing_after_failures: int = 3
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.interval_seconds < 300:
            raise ValueError("refresh interval must be at least 300 seconds")
        if self.missing_after_failures < 1:
            raise ValueError("missing_after_failures must be positive")

    def as_dict(self) -> dict[str, object]:
        return {
            "interval_seconds": self.interval_seconds,
            "missing_after_failures": self.missing_after_failures,
            "enabled": self.enabled,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object] | None) -> RefreshPolicy:
        raw = dict(value or {})
        return cls(
            interval_seconds=int(raw.get("interval_seconds", 86400)),
            missing_after_failures=int(raw.get("missing_after_failures", 3)),
            enabled=bool(raw.get("enabled", True)),
        )

    def next_at(self, now: datetime | None = None) -> datetime | None:
        if not self.enabled:
            return None
        base = now or datetime.now(UTC)
        return base + timedelta(seconds=self.interval_seconds)


@dataclass(frozen=True, slots=True)
class RefreshResult:
    refresh_run_id: str
    resource_id: str
    outcome: str
    changed: bool
    previous_hash: str | None
    current_hash: str | None
    next_refresh_at: datetime | None
    detail: Mapping[str, object]
