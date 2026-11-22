from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ingest_slo_qwen_stage_run as runmod  # noqa: E402


def test_fixed_runner_is_cpu_only_nonprod_and_bounded() -> None:
    args = runmod.llama_arguments()
    assert args[0] == "/opt/homebrew/bin/llama-server"
    assert args[args.index("--port") + 1] == "18190"
    assert args[args.index("--host") + 1] == "127.0.0.1"
    assert args[args.index("--n-gpu-layers") + 1] == "0"
    assert args[args.index("--threads") + 1] == "2"
    assert args[args.index("--parallel") + 1] == "1"
    assert "--embedding" in args
    assert "--no-webui" in args
    assert "8090" not in args
    assert runmod.MAX_ROWS == 80
    assert runmod.MAX_RUN_SECONDS <= 420


@pytest.mark.parametrize("length", [128, 512])
def test_only_synthetic_fixed_size_chunks(length) -> None:
    chunks = runmod.synthetic_chunks(length, 7)
    assert len(chunks) == 8
    assert all(len(c) == length and "synthetic" in c for c in chunks)


@pytest.mark.parametrize(("length", "index"), [(0, 0), (8192, 1), (128, -1), (128, 10000)])
def test_bad_synthetic_profiles_rejected(length, index) -> None:
    with pytest.raises(ValueError):
        runmod.synthetic_chunks(length, index)


def test_balanced_plan_has_exact_20_per_cell() -> None:
    plan = runmod.planned_cells()
    assert len(plan) == 80
    assert plan == runmod.planned_cells()
    assert len(set(plan)) == 80
    assert plan[0] != (128, 1, 0)
    for length in (128, 512):
        for concurrency in (1, 4):
            assert sum(x == length and y == concurrency for x, y, _ in plan) == 20


def test_aggregates_have_no_source_fields_and_no_prod_slo_claim():
    rows = [
        {"chunk_chars": length, "concurrency": concurrency, "latency_ms": 1000 + length}
        for length in (128, 512)
        for concurrency in (1, 4)
        for _ in range(20)
    ]
    result = runmod.aggregate(rows)
    assert result["requests"] == 80
    assert not result["production_latency_comparable"]
    assert not result["production_slo_proven"]
    assert not result["queue_latency_separately_measured"]
    assert result["cells_p95_ms"]["chunk_chars_128_concurrency_1"] == 1128
    assert "embedding" not in json.dumps(result)


def test_incomplete_cohorts_fail_closed():
    with pytest.raises(runmod.StageAborted, match="staging_incomplete_sample_count"):
        runmod.aggregate([{"chunk_chars": 128, "concurrency": 1, "latency_ms": 1000}])


def test_reduced_governor_never_starts_a_model(monkeypatch):
    monkeypatch.setattr(runmod, "live_preflight", lambda: {
        "admission": "blocked",
        "reason_codes": ["governor_not_normal", "swap_used_too_high_or_unknown"],
    })
    def forbidden(*a, **kw):
        raise AssertionError("must not start Qwen under a blocked admission")
    monkeypatch.setattr(runmod.subprocess, "Popen", forbidden)
    with pytest.raises(runmod.StageAborted, match="resource_admission_blocked"):
        runmod.run()


def test_stage_endpoint_never_equals_production():
    assert runmod.HOST == "http://127.0.0.1:18190"
    assert "8090" not in runmod.HOST
    assert runmod.CHUNKS_PER_REQUEST == 8


def test_watchdog_trips_when_governor_becomes_reduced(monkeypatch):
    import threading
    monkeypatch.setattr(runmod, "live_preflight", lambda: {
        "admission": "blocked", "reason_codes": ["governor_not_normal", "stage_port_in_use"]
    })
    stop, tripped = threading.Event(), threading.Event()
    monkeypatch.setattr(stop, "wait", lambda _: False)
    runmod._watch_resources(stop, tripped)
    assert tripped.is_set()
