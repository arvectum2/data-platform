"""Bounded, content-free per-request ingest timing for local SLO diagnosis.

No document text, URI, collection ID, credentials or filenames are stored.
Metrics are generated only while serving an actual ingest HTTP request.
"""

from __future__ import annotations

import math
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

from ..supportability import percentile

PHASES = ("prepare", "lookup", "embedding", "persist")
SIZE_BUCKETS = ("up_to_8kib", "up_to_64kib", "up_to_256kib", "above_256kib", "unknown")
_ACTIVE: ContextVar[IngestTrace | None] = ContextVar("dp_ingest_trace", default=None)


@dataclass
class IngestTrace:
    phases_ms: dict[str, float] = field(default_factory=lambda: {name: 0.0 for name in PHASES})
    size_bucket: str = "unknown"
    concurrency: int = 1
    chunks: int = 0
    embedding_attempts: int = 0
    embedding_batches: int = 0
    embedding_retries: int = 0
    total_ms: int = 0
    status_code: int = 500

    def numeric_sample(self) -> dict[str, Any]:
        return {
            "phases_ms": {name: math.ceil(self.phases_ms[name]) for name in PHASES},
            "size_bucket": self.size_bucket,
            "concurrency": max(1, self.concurrency),
            "chunks": max(0, self.chunks),
            "embedding_attempts": max(0, self.embedding_attempts),
            "embedding_batches": max(0, self.embedding_batches),
            "embedding_retries": max(0, self.embedding_retries),
            "total_ms": max(0, self.total_ms),
            "status_code": self.status_code,
        }


def begin(trace: IngestTrace) -> Token[IngestTrace | None]:
    return _ACTIVE.set(trace)


def end(token: Token[IngestTrace | None]) -> None:
    _ACTIVE.reset(token)


def observe_input_size(byte_count: int) -> None:
    trace = _ACTIVE.get()
    if trace is None:
        return
    if byte_count <= 8192:
        trace.size_bucket = "up_to_8kib"
    elif byte_count <= 65536:
        trace.size_bucket = "up_to_64kib"
    elif byte_count <= 262144:
        trace.size_bucket = "up_to_256kib"
    else:
        trace.size_bucket = "above_256kib"


def observe_chunks(count: int) -> None:
    trace = _ACTIVE.get()
    if trace is not None:
        trace.chunks = max(0, count)


def observe_embedding_attempts(count: int) -> None:
    trace = _ACTIVE.get()
    if trace is not None:
        trace.embedding_attempts = max(0, count)


def observe_embedding_batch_start() -> None:
    """Count unique batch submissions, including a failed final batch."""
    trace = _ACTIVE.get()
    if trace is not None:
        trace.embedding_batches += 1


def observe_embedding_retry() -> None:
    """Count actual repeat submissions, not normal consecutive batches."""
    trace = _ACTIVE.get()
    if trace is not None:
        trace.embedding_retries += 1


@contextmanager
def timed_phase(name: str) -> Iterator[None]:
    if name not in PHASES:
        raise ValueError("unrecognized ingest timing phase")
    trace = _ACTIVE.get()
    if trace is None:
        yield
        return
    started = time.perf_counter_ns()
    try:
        yield
    finally:
        trace.phases_ms[name] += max(0.0, (time.perf_counter_ns() - started) / 1_000_000)


def timed_call(phase: str, function: Any, *args: Any, **kwargs: Any) -> Any:
    with timed_phase(phase):
        return function(*args, **kwargs)


@contextmanager
def timed_session(factory: Any, phase: str) -> Iterator[Any]:
    with timed_phase(phase):
        with factory() as session:
            yield session


def _aggregate(samples: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(samples)
    p95s = {
        phase: percentile([sample["phases_ms"][phase] for sample in samples], 0.95)
        for phase in PHASES
    }
    errors = sum(item["status_code"] >= 400 for item in samples)
    return {
        "samples": n,
        "sufficient_samples": n >= 20,
        "phase_p95_ms": p95s,
        "request_p95_ms": percentile([item["total_ms"] for item in samples], 0.95),
        "errors": errors,
        "window_error_rate": round(errors / n, 6) if n else None,
        "embedding_attempts_sum": sum(item["embedding_attempts"] for item in samples),
        # Keep legacy attempts unchanged. Batches and retries are separately
        # observed during inference, including an unsuccessful final batch.
        "embedding_batches_sum": sum(item.get("embedding_batches", 0) for item in samples),
        "embedding_retries_sum": sum(item.get("embedding_retries", 0) for item in samples),
        "requests_with_embedding_retries": sum(
            item.get("embedding_retries", 0) > 0 for item in samples
        ),
        "chunks_sum": sum(item["chunks"] for item in samples),
    }


def phase_readiness(samples: Any) -> dict[str, Any]:
    rows = list(samples)
    result = {
        "scope": "ingest_http_numeric_only",
        "content_included": False,
        "total": _aggregate(rows),
        "by_input_size": {},
        "by_concurrency": {},
        "by_chunk_count": {},
        "note": (
            "Chunk cohorts are diagnostic only, not approved per-cohort SLOs. "
            "Incomplete ingest with unknown chunk count is separated from zero inference. "
            "Phase data alone cannot prove causal attribution or production SLO."
        ),
    }
    for bucket in SIZE_BUCKETS:
        group = [row for row in rows if row["size_bucket"] == bucket]
        if group:
            result["by_input_size"][bucket] = _aggregate(group)
    for name, check in (
        ("one", lambda value: value == 1),
        ("two_to_four", lambda value: 2 <= value <= 4),
        ("five_plus", lambda value: value >= 5),
    ):
        group = [row for row in rows if check(row["concurrency"])]
        if group:
            result["by_concurrency"][name] = _aggregate(group)
    chunk_checks = (
        ("unknown_or_zero", lambda value: value == 0),
        ("one_to_three", lambda value: 1 <= value <= 3),
        ("four_to_eight", lambda value: 4 <= value <= 8),
        ("nine_to_sixteen", lambda value: 9 <= value <= 16),
        ("seventeen_plus", lambda value: value >= 17),
    )
    for name, check in chunk_checks:
        group = [row for row in rows if check(row["chunks"])]
        if group:
            result["by_chunk_count"][name] = _aggregate(group)
    return result
