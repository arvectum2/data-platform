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
    plan = runmod.planned_blocks()
    assert len(plan) == 20
    assert plan == runmod.planned_blocks()
    assert len(set(plan)) == 20
    assert all(len(numbers) == 4 for _, _, numbers in plan)
    for length in (128, 512):
        for concurrency in (1, 4):
            numbers = [
                number
                for x, y, group in plan if x == length and y == concurrency
                for number in group
            ]
            assert sorted(numbers) == list(range(20))


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

def test_generated_chunks_have_distinct_content_within_a_batch():
    chunks = runmod.synthetic_chunks(128, 9)
    assert len(set(chunks)) == 8


def test_bounded_http_embedding_validates_response_and_never_uses_live_port(monkeypatch):
    import urllib.request

    payloads = []
    class Response:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, length):
            assert length == runmod.MAX_HTTP_BYTES + 1
            return json.dumps({
                "data": [{"embedding": [0.1, 0.2], "index": i} for i in range(8)]
            }).encode()

    class Opener:
        def open(self, req, timeout):
            assert req.full_url == "http://127.0.0.1:18190/v1/embeddings"
            assert req.get_method() == "POST"
            payload = json.loads(req.data)
            assert payload["model"] == runmod.ALIAS
            assert len(payload["input"]) == 8
            assert len(set(payload["input"])) == 8
            payloads.append(payload["model"])
            return Response()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: Opener())
    ms, count = runmod._embed_once(runmod.synthetic_chunks(128, 3))
    assert ms >= 0
    assert count == 8
    assert payloads == [runmod.ALIAS]


def test_invalid_model_response_fails_closed(monkeypatch):
    import urllib.request

    class Response:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, _):
            return b'{"data":[{"embedding":[0.1]}]}'

    class Opener:
        def open(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: Opener())
    with pytest.raises(runmod.StageAborted, match="staging_embedding_response_invalid"):
        runmod._embed_once(runmod.synthetic_chunks(128, 3))

def test_cli_refuses_execute_with_clear_no_launch_claim(monkeypatch, capsys):
    monkeypatch.setattr(runmod, "live_preflight", lambda: {
        "admission": "blocked",
        "reason_codes": ["governor_not_normal"],
    })
    monkeypatch.setattr(sys, "argv", ["stage", "--execute"])

    def forbidden(*a, **kw):
        raise AssertionError("must not launch a model when admission denied")

    monkeypatch.setattr(runmod.subprocess, "Popen", forbidden)
    assert runmod.main() == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked_or_failed"
    assert payload["reason_code"] == "resource_admission_blocked"
    assert payload["isolated_stage_launch_may_have_occurred"] is False
    assert payload["production_http_requests_sent"] is False
    assert payload["production_database_writes"] == 0

def test_resource_monitor_starts_during_model_load_and_aborts_before_health(monkeypatch):
    launched = []
    class Child:
        def poll(self):
            return None
        def terminate(self):
            launched.append("terminated")
        def wait(self, timeout):
            launched.append("waited")

    class ImmediatePressureMonitor:
        def __init__(self, target, args, daemon):
            assert target is runmod._watch_resources
            assert daemon is True
            self.stop, self.tripped = args
        def start(self):
            launched.append("monitor_started")
            self.tripped.set()
        def join(self, timeout):
            launched.append("monitor_joined")

    monkeypatch.setattr(runmod, "live_preflight", lambda: {
        "admission": "pass",
        "reason_codes": [],
    })
    monkeypatch.setattr(runmod.subprocess, "Popen", lambda *_args, **_kwargs: Child())
    monkeypatch.setattr(runmod.threading, "Thread", ImmediatePressureMonitor)
    def forbidden_health():
        raise AssertionError("resource trip must abort before any health or embedding HTTP")
    monkeypatch.setattr(runmod, "_http_get_health", forbidden_health)
    with pytest.raises(runmod.StageAborted, match="resource_or_time_limit_during_startup"):
        runmod.run()
    assert launched == ["monitor_started", "terminated", "waited", "monitor_joined"]


def test_ci_postgres_guard_requires_exact_local_ephemeral_fixture():
    source = (
        Path(__file__).resolve().parents[1] /
        "tests/api/test_ingest_tx_connection_postgres.py"
    ).read_text()
    assert '"GITHUB_ACTIONS"' in source
    assert "database_url != allowed_ci_dsn" in source
    assert '("arvectum_ci", "arvectum_ci")' in source
    assert "postgresql+psycopg://arvectum_ci:local_ci_only" in source
