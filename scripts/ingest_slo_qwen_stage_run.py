"""Bounded CPU-only Qwen3-Embedding-4B stage, only after live resource admission.

NOT production-equivalent latency: CPU-only isolated model != live GPU backend.
Use generated synthetic chunks; no DB, no external URL, no live model port.
Never execute when the governor or swap gate is unsafe.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from ingest_slo_qwen_stage_gate import BINARY, MODEL, live_preflight

HOST = "http://127.0.0.1:18190"
ALIAS = "Qwen3-Embedding-4B-isolated"
CHUNK_LENGTHS = (128, 512)
CHUNKS_PER_REQUEST = 8
CONCURRENCIES = (1, 4)
SAMPLES_PER_CELL = 20
WARMUP_REQUESTS = 2
MAX_ROWS = 80
MAX_RUN_SECONDS = 420
REQUEST_TIMEOUT_SECONDS = 45
MAX_HTTP_BYTES = 2_000_000


class StageAborted(RuntimeError):
    pass


def llama_arguments() -> list[str]:
    """Fixed target, model, bounds and loopback: no arbitrary command fields."""
    return [
        str(BINARY), "--model", str(MODEL), "--alias", ALIAS,
        "--host", "127.0.0.1", "--port", "18190",
        "--embedding", "--no-webui", "--metrics",
        "--threads", "2", "--threads-batch", "2",
        "--n-gpu-layers", "0", "--ctx-size", "4096",
        "--parallel", "1",
    ]


def synthetic_chunks(length: int, number: int) -> list[str]:
    if length not in CHUNK_LENGTHS or not 0 <= number < 10_000:
        raise ValueError("unapproved synthetic profile")
    prefix = f"synthetic staging vector probe number {number:04d} "
    return [
        (
            (prefix + f" distinct synthetic chunk {index} ")
            * ((length // len(prefix + f" distinct synthetic chunk {index} ")) + 1)
        )[:length]
        for index in range(CHUNKS_PER_REQUEST)
    ]


def planned_blocks() -> list[tuple[int, int, tuple[int, ...]]]:
    """Five counterbalanced blocks per profile, four distinct calls per block."""
    blocks = [
        (length, concurrency, tuple(range(round_index * 4, round_index * 4 + 4)))
        for round_index in range(SAMPLES_PER_CELL // 4)
        for length in CHUNK_LENGTHS
        for concurrency in CONCURRENCIES
    ]
    random.Random(20261122).shuffle(blocks)
    assert sum(len(numbers) for _, _, numbers in blocks) == MAX_ROWS
    return blocks


def _http_get_health() -> bool:
    req = urllib.request.Request(HOST + "/health", method="GET")
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            req, timeout=2
        ) as response:
            return response.status == 200 and len(response.read(512)) <= 512
    except (OSError, urllib.error.URLError):
        return False


def _embed_once(chunks: list[str]) -> tuple[int, int]:
    payload = json.dumps(
        {"input": chunks, "model": ALIAS}, separators=(",", ":")
    ).encode("utf-8")
    req = urllib.request.Request(
        HOST + "/v1/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter_ns()
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            req, timeout=REQUEST_TIMEOUT_SECONDS
        ) as response:
            if response.status != 200:
                raise StageAborted("staging_embedding_http_not_200")
            raw = response.read(MAX_HTTP_BYTES + 1)
    except (OSError, urllib.error.URLError) as exc:
        raise StageAborted("staging_embedding_request_failed") from exc
    if len(raw) > MAX_HTTP_BYTES:
        raise StageAborted("staging_embedding_response_too_large")
    try:
        result = json.loads(raw)
        rows = result["data"]
        if not isinstance(rows, list) or len(rows) != len(chunks):
            raise ValueError
        if not all(isinstance(row.get("embedding"), list) and row["embedding"] for row in rows):
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise StageAborted("staging_embedding_response_invalid") from exc
    elapsed_ms = math.ceil((time.perf_counter_ns() - started) / 1_000_000)
    # Never serialize or expose the embedding vectors, inputs or private data.
    return elapsed_ms, len(rows)


def _p95(values: list[int]) -> int:
    ordered = sorted(values)
    position = (len(ordered) - 1) * 0.95
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return int(round(ordered[lower] * (1 - (position - lower)) + ordered[upper] * (position - lower)))


def aggregate(rows: list[dict[str, int]]) -> dict[str, object]:
    if len(rows) != MAX_ROWS:
        raise StageAborted("staging_incomplete_sample_count")
    buckets: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        bucket = f"chunk_chars_{row['chunk_chars']}_concurrency_{row['concurrency']}"
        buckets[bucket].append(row["latency_ms"])
    if len(buckets) != 4 or any(len(values) != SAMPLES_PER_CELL for values in buckets.values()):
        raise StageAborted("staging_incomplete_per_cell")
    return {
        "status": "synthetic_model_stage_only",
        "model": ALIAS,
        "provider_backend": "CPU_only_isolated",
        "production_model_endpoint_used": False,
        "production_latency_comparable": False,
        "production_slo_proven": False,
        "model_vectors_saved": False,
        "requests": MAX_ROWS,
        "samples_per_cell": SAMPLES_PER_CELL,
        "overall_p95_ms": _p95([row["latency_ms"] for row in rows]),
        "cells_p95_ms": {key: _p95(v) for key, v in sorted(buckets.items())},
        "cells_max_ms": {key: max(v) for key, v in sorted(buckets.items())},
        "queue_latency_separately_measured": False,
    }


def _watch_resources(stop: threading.Event, tripped: threading.Event) -> None:
    while not stop.wait(3):
        report = live_preflight()
        # Stage port is now legitimately bound by our isolated server; don't
        # treat that one startup-only precondition as runtime failure.
        unsafe = set(report.get("reason_codes", [])) - {"stage_port_in_use"}
        if unsafe:
            tripped.set()
            return


def run() -> dict[str, object]:
    admission = live_preflight()
    if admission["admission"] != "pass":
        raise StageAborted("resource_admission_blocked")
    if sum(len(numbers) for _, _, numbers in planned_blocks()) != MAX_ROWS:
        raise StageAborted("unapproved_sample_budget")
    started = time.monotonic()
    stop = threading.Event()
    tripped = threading.Event()
    # Restrict environment inherited by the isolated model process.
    clean_env = {
        "PATH": "/opt/homebrew/bin:/usr/bin:/bin",
        "HOME": "/tmp",
        "LANG": "C",
    }
    child: subprocess.Popen[bytes] | None = None
    watchdog: threading.Thread | None = None
    try:
        # No production ports, model writes, global service or config changes.
        child = subprocess.Popen(
            llama_arguments(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=clean_env,
            cwd="/tmp",
            start_new_session=True,
        )
        startup_end = time.monotonic() + 90
        while time.monotonic() < startup_end:
            if child.poll() is not None:
                raise StageAborted("isolated_model_exited_before_ready")
            if _http_get_health():
                break
            time.sleep(1)
        else:
            raise StageAborted("isolated_model_startup_timeout")
        watchdog = threading.Thread(target=_watch_resources, args=(stop, tripped), daemon=True)
        watchdog.start()
        for i in range(WARMUP_REQUESTS):
            if tripped.is_set() or time.monotonic() - started > MAX_RUN_SECONDS:
                raise StageAborted("resource_or_time_limit_during_warmup")
            _embed_once(synthetic_chunks(CHUNK_LENGTHS[i % 2], i))
        rows: list[dict[str, int]] = []
        # Repeated interleaved balanced blocks, rather than four cold-first
        # contiguous cohorts. Every block has four distinct synthetic calls.
        for length, concurrency, numbers in planned_blocks():
            if tripped.is_set() or time.monotonic() - started > MAX_RUN_SECONDS:
                raise StageAborted("resource_or_time_limit")
            executor = ThreadPoolExecutor(max_workers=concurrency)
            try:
                jobs = [
                    executor.submit(_embed_once, synthetic_chunks(length, number + 2))
                    for number in numbers
                ]
                for job in jobs:
                    if tripped.is_set() or time.monotonic() - started > MAX_RUN_SECONDS:
                        raise StageAborted("resource_or_time_limit")
                    elapsed_ms, vectors = job.result(timeout=REQUEST_TIMEOUT_SECONDS + 2)
                    if vectors != CHUNKS_PER_REQUEST:
                        raise StageAborted("unexpected_embedded_chunk_count")
                    rows.append({
                        "chunk_chars": length,
                        "concurrency": concurrency,
                        "latency_ms": elapsed_ms,
                    })
            except BaseException:
                # Never enqueue further traffic after a resource trip.
                executor.shutdown(wait=False, cancel_futures=True)
                raise
            else:
                executor.shutdown(wait=True)
        report = aggregate(rows)
        report["stage_duration_seconds"] = round(time.monotonic() - started, 2)
        report["completed_at_utc"] = datetime.now(UTC).isoformat()
        return report
    finally:
        stop.set()
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
        if watchdog is not None:
            watchdog.join(timeout=3)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({
            "status": "dry_run_only",
            "model_launch_executed": False,
            "admission": live_preflight(),
            "note": "explicit --execute required, and only after admission passes",
        }, sort_keys=True))
        return 0
    try:
        report = run()
    except (StageAborted, subprocess.TimeoutExpired, OSError) as exc:
        # Only an allowlisted error-code/category goes to stdout, never raw errors.
        allowed = {
            "resource_admission_blocked",
            "unapproved_sample_budget",
            "isolated_model_exited_before_ready",
            "isolated_model_startup_timeout",
            "resource_or_time_limit",
            "resource_or_time_limit_during_warmup",
            "staging_incomplete_sample_count",
            "staging_incomplete_per_cell",
            "unexpected_embedded_chunk_count",
        }
        code = str(exc) if isinstance(exc, StageAborted) and str(exc) in allowed else "stage_aborted"
        print(json.dumps({
            "status": "blocked_or_failed",
            "reason_code": code,
            "production_http_requests_sent": False,
            "production_database_writes": 0,
            "isolated_stage_launch_may_have_occurred": code != "resource_admission_blocked",
        }))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
