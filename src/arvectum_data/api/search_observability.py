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
_MODES = ("lexical", "vector", "hybrid", "unknown")


def numeric_search_sample(
    stages: Iterable[object],
    *,
    mode: str | None = None,
    rerank_requested: bool | None = None,
    expansion_requested: bool | None = None,
) -> dict[str, Any] | None:
    """Accept only finite timing and fixed request-mode/feature cohorts.

    Source content, provider/model, source IDs, query text and metadata
    are not retained. Missing legacy mode remains an explicit unknown.
    """

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
    sample: dict[str, Any] = {"stages_ms": result}
    if mode is not None:
        # Persist a literal category only, never caller-supplied strings.
        sample["mode"] = next(
            (name for name in _MODES[:3] if name == mode), "unknown"
        )
    if type(rerank_requested) is bool:
        sample["rerank_requested"] = rerank_requested
    if type(expansion_requested) is bool:
        sample["expansion_requested"] = expansion_requested
    return sample


def _summarize_phase_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, list[int]] = {name: [] for name in PHASES}
    for row in rows:
        stages = row["stages_ms"]
        for name in PHASES:
            value = stages.get(name)
            if type(value) is int and 0 <= value <= _MAX_MS:
                buckets[name].append(value)
    return {
        "samples": len(rows),
        "sufficient_samples": len(rows) >= 20,
        "stage_samples": {name: len(values) for name, values in buckets.items()},
        "stage_sufficient_samples": {
            name: len(values) >= 20 for name, values in buckets.items()
        },
        "stage_p95_ms": {
            name: percentile(values, 0.95) if values else None
            for name, values in buckets.items()
        },
    }


def search_phase_readiness(samples: Iterable[object]) -> dict[str, Any]:
    """Report safe, bounded search-stage cohorts, never infer an HTTP SLO."""
    valid_rows: list[dict[str, Any]] = []
    for raw in list(samples)[-_MAX_SAMPLES:]:
        if not isinstance(raw, dict):
            continue
        stages = raw.get("stages_ms")
        if not isinstance(stages, dict):
            continue
        total = stages.get("total-search")
        if type(total) is not int or total < 0 or total > _MAX_MS:
            continue
        valid_rows.append(raw)
    result = {
        **_summarize_phase_rows(valid_rows),
        "window_size": _MAX_SAMPLES,
        "by_mode": {},
        "by_rerank_requested": {},
        "by_expansion_requested": {},
        "content_included": False,
        "note": (
            "successful search stages only; cohort p95 requires >=20 per cohort; "
            "mode and feature groups overlap; phase p95 cannot be summed; "
            "not an HTTP SLO, current-production proof or causality verdict"
        ),
    }
    for mode in _MODES:
        rows = [
            row for row in valid_rows
            if (
                row.get("mode") == mode
                if mode != "unknown"
                else row.get("mode") not in _MODES[:3]
            )
        ]
        if rows:
            result["by_mode"][mode] = _summarize_phase_rows(rows)
    for flag, output in (
        ("rerank_requested", "by_rerank_requested"),
        ("expansion_requested", "by_expansion_requested"),
    ):
        for state, label in ((True, "yes"), (False, "no")):
            rows = [row for row in valid_rows if row.get(flag) is state]
            if rows:
                result[output][label] = _summarize_phase_rows(rows)
    return result
