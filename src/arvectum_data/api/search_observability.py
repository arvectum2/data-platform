"""Bounded, content-free search stage telemetry from completed search calls.

Never persist query text, identifiers, URLs, model/provider names or source
metadata. HTTP search SLO remains the independent authoritative metric.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from ..supportability import percentile

PHASES = (
    "query-expansion",
    "terminology-expansion",
    "embedding-query",
    "lexical-retrieval",
    "vector-retrieval",
    "fusion",
    "product-ranker",
    "rerank",
    "total-search",
)
_ALLOWED = frozenset(PHASES)
_MAX_MS = 3_600_000
_MAX_SAMPLES = 256


def numeric_search_sample(stages: Iterable[object]) -> dict[str, dict[str, int]] | None:
    """Accept only executed, finite stage durations and fixed stage names."""
    result: dict[str, int] = {}
    for item in stages:
        name = getattr(item, "stage", None)
        if not isinstance(name, str) or name not in _ALLOWED:
            continue
        if getattr(item, "status", None) != "executed":
            continue
        duration = getattr(item, "duration_ms", None)
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or duration < 0
            or duration > _MAX_MS
        ):
            continue
        # Only safe numeric phase counters enter the in-memory ring buffer.
        result[name] = min(_MAX_MS, result.get(name, 0) + math.ceil(duration))
    if "total-search" not in result:
        return None
    return {"stages_ms": result}


def search_phase_readiness(samples: Iterable[object]) -> dict[str, Any]:
    """Report successful-call stage timings separately from full HTTP p95."""
    buckets: dict[str, list[int]] = {name: [] for name in PHASES}
    valid = 0
    for raw in list(samples)[-_MAX_SAMPLES:]:
        if not isinstance(raw, dict):
            continue
        stages = raw.get("stages_ms")
        if not isinstance(stages, dict):
            continue
        total = stages.get("total-search")
        if type(total) is not int or total < 0 or total > _MAX_MS:
            continue
        valid += 1
        for name in PHASES:
            value = stages.get(name)
            if type(value) is int and 0 <= value <= _MAX_MS:
                buckets[name].append(value)
    return {
        "samples": valid,
        "window_size": _MAX_SAMPLES,
        "sufficient_samples": valid >= 20,
        "stage_samples": {name: len(values) for name, values in buckets.items()},
        "stage_sufficient_samples": {name: len(values) >= 20 for name, values in buckets.items()},
        "stage_p95_ms": {
            name: percentile(values, 0.95) if values else None
            for name, values in buckets.items()
        },
        "content_included": False,
        "note": "successful search stages only; not an HTTP SLO or causality verdict",
    }
