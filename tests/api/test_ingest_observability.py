"""Numeric-only ingest diagnostics; no documents, IDs or credentials in traces."""

from __future__ import annotations

import asyncio
import json
import time

import anyio

from arvectum_data.api.ingest_observability import (
    IngestTrace,
    begin,
    end,
    observe_chunks,
    observe_embedding_attempts,
    observe_input_size,
    phase_readiness,
    timed_call,
    timed_phase,
)


def test_empty_readiness_is_not_false_green() -> None:
    data = phase_readiness([])
    assert data["total"]["samples"] == 0
    assert data["total"]["sufficient_samples"] is False
    assert data["total"]["phase_p95_ms"]["embedding"] == 0


def test_traces_are_bounded_numeric_and_never_store_source_text() -> None:
    trace = IngestTrace(concurrency=3)
    token = begin(trace)
    private = "sensitive-source-uri-and-billing-token"
    try:
        observe_input_size(len(private.encode()))
        observe_chunks(2)
        observe_embedding_attempts(3)
        with timed_phase("embedding"):
            result = timed_call("prepare", lambda source: len(source), private)
        assert result == len(private)
    finally:
        end(token)
    trace.total_ms = 10
    trace.status_code = 200
    sample = trace.numeric_sample()
    assert sample["size_bucket"] == "up_to_8kib"
    assert sample["embedding_attempts"] == 3
    assert sample["chunks"] == 2
    report = phase_readiness([sample] * 20)
    assert report["total"]["samples"] == 20
    assert report["total"]["sufficient_samples"] is True
    assert report["by_concurrency"]["two_to_four"]["samples"] == 20
    assert report["by_input_size"]["up_to_8kib"]["samples"] == 20
    assert private not in json.dumps(report)
    assert all(isinstance(v, int) for v in sample["phases_ms"].values())


def test_failed_operation_records_elapsed_time_and_clears_context() -> None:
    trace = IngestTrace()
    token = begin(trace)
    try:
        try:
            with timed_phase("embedding"):
                time.sleep(0.002)
                raise RuntimeError("synthetic error")
        except RuntimeError:
            pass
    finally:
        end(token)
    assert trace.numeric_sample()["phases_ms"]["embedding"] >= 2
    with timed_phase("embedding"):
        time.sleep(0.001)
    assert trace.numeric_sample()["phases_ms"]["embedding"] >= 2


def test_context_is_propagated_to_bounded_worker_thread() -> None:
    async def scenario() -> IngestTrace:
        trace = IngestTrace()
        token = begin(trace)
        try:
            await anyio.to_thread.run_sync(lambda: timed_call("embedding", time.sleep, 0.003))
            return trace
        finally:
            end(token)

    result = asyncio.run(scenario())
    assert result.numeric_sample()["phases_ms"]["embedding"] >= 3


def test_cohorts_distinguish_small_medium_large_and_unknown_ingest() -> None:
    """Cohort rates belong to the same cohort; zero chunks can mean early error."""
    counts = [0] * 2 + [2] * 20 + [5] * 20 + [10] * 20 + [18] * 20
    rows = []
    for count in counts:
        rows.append(
            {
                "chunks": count,
                "embedding_attempts": 0 if count == 0 else 1,
                "concurrency": 1,
                "size_bucket": "up_to_8kib" if count < 4 else "up_to_64kib",
                "phases_ms": {name: 0 for name in ("prepare", "lookup", "embedding", "persist")},
                "total_ms": count * 1000,
                "status_code": 500 if count == 0 else 200,
            }
        )
    report = phase_readiness(rows)
    buckets = report["by_chunk_count"]
    assert report["total"]["samples"] == len(counts)
    assert report["total"]["window_error_rate"] == round(2 / len(counts), 6)
    assert buckets["unknown_or_zero"]["samples"] == 2
    assert buckets["unknown_or_zero"]["sufficient_samples"] is False
    assert buckets["unknown_or_zero"]["window_error_rate"] == 1.0
    assert buckets["one_to_three"]["samples"] == 20
    assert buckets["one_to_three"]["request_p95_ms"] == 2000
    assert buckets["four_to_eight"]["request_p95_ms"] == 5000
    assert buckets["nine_to_sixteen"]["request_p95_ms"] == 10000
    assert buckets["seventeen_plus"]["request_p95_ms"] == 18000
    assert all(
        buckets[name]["window_error_rate"] == 0
        for name in ("one_to_three", "four_to_eight", "nine_to_sixteen", "seventeen_plus")
    )
    assert sum(bucket["samples"] for bucket in buckets.values()) == len(counts)


def test_cohort_readiness_handles_empty_group() -> None:
    empty = phase_readiness([])
    assert empty["by_chunk_count"] == {}
    assert empty["total"]["window_error_rate"] is None
    assert empty["total"]["sufficient_samples"] is False
