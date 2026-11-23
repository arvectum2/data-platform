"""One-window synthetic TEXT ingest against existing Qwen and strictly disposable PG17.

Operator action only. No model launch/restart, no production DB or corpus access.
Temporarily disables future starts of one allowlisted periodic Tender Agent job,
and restores it in a finally block (with an independent one-shot failsafe).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from disposable_http_e2e import port, sh, stop
from arvectum_data.supportability import percentile

ROOT = Path(__file__).resolve().parent.parent
LABEL = "arvectum.dp.live_qwen_stage"
MODEL_URL = "http://127.0.0.1:8090/v1"
TA_JOB = "com.arvectum.tender-agent-technical-sibur"
SIZES = (5000,) * 9 + (11000,) * 8 + (22000,) * 2 + (62000,)
SERVER = """
import os,uvicorn
from arvectum_data.api.app import create_app
from arvectum_data.api.config import Settings
settings=Settings(_env_file=None,environment="test",deployment_mode="local-private",
 log_level="WARNING", database_url=os.environ["BENCH_DB"],
 internal_api_key=os.environ["BENCH_KEY"],
 embedding_provider="llama_cpp", embedding_model="Qwen3-Embedding-4B",
 embedding_base_url="http://127.0.0.1:8090/v1",
 embedding_dimension=2560, embedding_timeout_seconds=60,
 embedding_inference_batch_size=8, embedding_retry_max_attempts=1,
 cross_encoder_provider="disabled", reasoning_policy="disabled", vision_policy="disabled")
app=create_app(settings)
uvicorn.run(app,host="127.0.0.1",port=int(os.environ["BENCH_PORT"]),log_level="error")
"""


def ensure(value: bool, message: str) -> None:
    if not value:
        raise RuntimeError(message)


def health(url: str, timeout: float = 3) -> bool:
    try:
        with httpx.Client(timeout=timeout) as client:
            return client.get(url).status_code == 200
    except (httpx.HTTPError, OSError):
        return False


def swap_mib() -> float:
    output = subprocess.check_output(
        ["/usr/sbin/sysctl", "-n", "vm.swapusage"], text=True, timeout=5
    )
    match = re.search(r"used = ([\d.]+)M", output)
    ensure(match is not None, "swap telemetry missing")
    return float(match.group(1))


def synthetic_bytes(count: int, index: int) -> bytes:
    # No original files, resource titles, source IDs, tenant context or credentials.
    blocks = []
    total_bytes = 0
    section = 0
    while total_bytes < count:
        # Unique section markers prevent periodic source windows from deduplicating.
        # In contrast, repeated identical paragraphs collapse to 2 chunks at 60KiB.
        paragraph = (
            f"Синтетический раздел {index:03d}-{section:05d}: силовой кабель, "
            "проверка изоляции, монтаж, испытания, технический надзор, "
            "график выполнения работ, контроль и исполнительная документация. "
        ).encode("utf-8")
        blocks.append(paragraph)
        total_bytes += len(paragraph)
        section += 1
    return b"".join(blocks)[:count].decode("utf-8", errors="ignore").encode("utf-8")


@contextmanager
def pause_new_runs() -> None:
    uid = os.getuid()
    service = f"gui/{uid}/{TA_JOB}"
    # Never stop, signal or suspend an in-flight Tender Agent process.
    state = sh("launchctl", "print", service, timeout=5)
    ensure("state = " in state, "TA scheduler state unreadable")
    disabled = sh("launchctl", "print-disabled", f"gui/{uid}", timeout=5)
    ensure(f'"{TA_JOB}" => disabled' not in disabled, "TA job disabled before window")
    # Independent failsafe re-enables launches after 8 min if this process dies.
    # Kill and reap after normal restoration, never leave it running afterwards.
    watchdog = subprocess.Popen(
        ["/bin/zsh", "-c", f"sleep 480; /bin/launchctl enable {service}"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    paused = False
    try:
        # Treat a potentially ambiguous disable result as a mutation to undo.
        paused = True
        sh("launchctl", "disable", service, timeout=5)
        verify = sh("launchctl", "print-disabled", f"gui/{uid}", timeout=5)
        ensure(f'"{TA_JOB}" => disabled' in verify, "pause not verified")
        # Disabling scheduled *future* launches does not signal/kill the active task.
        # Let a current periodic run finish before applying any model load.
        for _ in range(25):
            state = sh("launchctl", "print", service, timeout=5)
            if "state = not running" in state:
                break
            time.sleep(3)
        else:
            raise RuntimeError("periodic Tender Agent job did not become idle")
        yield
    finally:
        restored = not paused
        try:
            if paused:
                sh("launchctl", "enable", service, timeout=8)
                verify = sh("launchctl", "print-disabled", f"gui/{uid}", timeout=5)
                ensure(f'"{TA_JOB}" => disabled' not in verify, "TA scheduler restoration failed")
                restored = True
        finally:
            # If restoration failed, retain the independent timed fallback.
            # Killing it here would strand the TA job disabled indefinitely.
            if restored:
                watchdog.terminate()
                try:
                    watchdog.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    watchdog.kill()
                    watchdog.wait(timeout=3)


def wait_api(env: dict[str, str], log_path: Path) -> subprocess.Popen[str]:
    environment = dict(env, PYTHONPATH=str(ROOT / "src"))
    with log_path.open("w") as out:
        proc = subprocess.Popen(
            [sys.executable, "-c", SERVER],
            cwd=ROOT,
            env=environment,
            stdout=out,
            stderr=subprocess.STDOUT,
        )
    for _ in range(60):
        if proc.poll() is not None:
            stop(proc)
            raise RuntimeError("isolated candidate API exited during startup")
        if health(f"http://127.0.0.1:{env['BENCH_PORT']}/health"):
            return proc
        time.sleep(0.25)
    stop(proc)
    raise RuntimeError("isolated candidate API health timeout")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-authorized-window", action="store_true")
    args = parser.parse_args()
    ensure(args.execute_authorized_window, "explicit window flag required")
    ensure(not (ROOT / ".env").exists(), "repository env file is not allowed")
    ensure(health("http://127.0.0.1:8090/health"), "live embedding server unavailable")
    ensure(health("http://127.0.0.1:8094/health"), "live Data Platform unavailable")
    ensure(health("http://127.0.0.1:8001/health"), "Tender Agent backend unavailable")
    baseline_swap = swap_mib()
    # Must match the real upload and chunking defaults before load starts.
    from arvectum_data.documents import ingest_bytes

    expected_chunks = []
    for index, size in enumerate(SIZES):
        generated = synthetic_bytes(size, index)
        result = ingest_bytes(
            generated,
            filename="generated.txt",
            collection_id="preflight:offline",
            canonical_uri=f"synthetic://preflight/{index}",
        )
        expected_chunks.append(len(result.chunks))
    ensure(len(expected_chunks) == 20, "incorrect sample count")
    ensure(min(expected_chunks) >= 2 and max(expected_chunks) >= 18, "unrepresentative chunk range")
    ensure(4 <= percentile(expected_chunks, 0.5) <= 8, "unrepresentative median chunks")
    print(
        json.dumps(
            {
                "preflight_chunk_range": [min(expected_chunks), max(expected_chunks)],
                "preflight_median_chunks": percentile(expected_chunks, 0.5),
                "synthetic_only": True,
            }
        ),
        flush=True,
    )
    uid = uuid.uuid4().hex[:10]
    container = f"dp-live-qwen-stage-{uid}"
    pg_user = f"stage_{uid}"
    pg_password = secrets.token_urlsafe(18)
    pgport, apiport = port(), port()
    ensure(pgport != apiport, "duplicate allocated ports")
    db_url = f"postgresql+psycopg://{pg_user}:{pg_password}@127.0.0.1:{pgport}/{pg_user}"
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("ARVECTUM_DATA_", "BENCH_", "E2E_"))
    }
    env.update(BENCH_DB=db_url, BENCH_KEY=secrets.token_urlsafe(24), BENCH_PORT=str(apiport))
    headers = {"X-Arvectum-Key": env["BENCH_KEY"]}
    collection = f"stage:synthetic:{uid}"
    api = None
    created = False
    readings: list[dict[str, int]] = []
    started = time.monotonic()
    stage_info: dict = {}
    with tempfile.TemporaryDirectory(prefix="dp-qwen-stage-") as dirname:
        wd = Path(dirname)
        try:
            with pause_new_runs():
                ensure(health("http://127.0.0.1:8090/health"), "Qwen down after pause")
                sh(
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    container,
                    "--label",
                    f"{LABEL}=true",
                    "--memory",
                    "384m",
                    "--cpus",
                    "1",
                    "-p",
                    f"127.0.0.1:{pgport}:5432",
                    "-e",
                    f"POSTGRES_USER={pg_user}",
                    "-e",
                    f"POSTGRES_PASSWORD={pg_password}",
                    "-e",
                    f"POSTGRES_DB={pg_user}",
                    "--health-cmd",
                    f"pg_isready -U {pg_user} -d {pg_user}",
                    "--health-interval",
                    "1s",
                    "--health-retries",
                    "30",
                    "pgvector/pgvector:pg17",
                    timeout=75,
                )
                created = True
                for _ in range(75):
                    if (
                        sh("docker", "inspect", "-f", "{{.State.Health.Status}}", container)
                        == "healthy"
                    ):
                        break
                    time.sleep(0.3)
                else:
                    raise RuntimeError("disposable DB did not become healthy")
                engine = create_engine(db_url)
                try:
                    with engine.connect() as conn:
                        identity = tuple(
                            conn.execute(text("select current_database(), current_user")).one()
                        )
                        ensure(
                            identity == (pg_user, pg_user), "isolated database identity mismatch"
                        )
                finally:
                    engine.dispose()
                # Alembic gets only this run's disposable DSN, never production credentials.
                previous = os.environ.get("ARVECTUM_DATA_DATABASE_URL")
                try:
                    os.environ["ARVECTUM_DATA_DATABASE_URL"] = db_url
                    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
                finally:
                    if previous is None:
                        os.environ.pop("ARVECTUM_DATA_DATABASE_URL", None)
                    else:
                        os.environ["ARVECTUM_DATA_DATABASE_URL"] = previous
                api = wait_api(env, wd / "api.log")
                with httpx.Client(base_url=f"http://127.0.0.1:{apiport}", timeout=70) as client:
                    result = client.post(
                        "/v1/collections",
                        headers=headers,
                        json={
                            "collection_id": collection,
                            "owner": "synthetic-stage",
                            "name": "Synthetic offline acceptance",
                            "default_language": "russian",
                        },
                    )
                    ensure(result.status_code == 200, "isolated collection not created")
                    for idx, length in enumerate(SIZES):
                        ensure(time.monotonic() - started < 450, "time budget exceeded")
                        ensure(swap_mib() <= baseline_swap + 512, "swap grew >512MiB")
                        ensure(health("http://127.0.0.1:8090/health"), "Qwen unhealthy")
                        ensure(health("http://127.0.0.1:8094/health"), "production unhealthy")
                        payload = synthetic_bytes(length, idx)
                        t0 = time.perf_counter_ns()
                        try:
                            response = client.post(
                                "/v1/ingest/document",
                                headers=headers,
                                data={
                                    "collection_id": collection,
                                    "canonical_uri": f"synthetic://disposable/{uid}/{idx}",
                                },
                                files={"file": ("generated.txt", payload, "text/plain")},
                            )
                            status = response.status_code
                        except httpx.HTTPError:
                            status = 599
                            response = None
                        ms = round((time.perf_counter_ns() - t0) / 1e6)
                        chunks = 0
                        if response is not None and status == 200:
                            chunks = int(response.json().get("chunks", 0))
                            ensure(
                                chunks == expected_chunks[idx],
                                "unexpected deduplication or chunking drift",
                            )
                        readings.append(
                            {
                                "bytes": len(payload),
                                "chunks": chunks,
                                "duration_ms": ms,
                                "http_status": status,
                            }
                        )
                        print(
                            json.dumps(
                                {
                                    "sample": idx + 1,
                                    "of": len(SIZES),
                                    "size_bucket": "small"
                                    if len(payload) <= 8192
                                    else "medium"
                                    if len(payload) <= 65536
                                    else "large",
                                    "chunks": chunks,
                                    "duration_ms": ms,
                                    "http_status": status,
                                },
                                sort_keys=True,
                            ),
                            flush=True,
                        )
                        if status != 200:
                            raise RuntimeError("one synthetic ingest request failed")
                    response = client.get("/v1/support/readiness", headers=headers)
                    ensure(response.status_code == 200, "phase readiness unavailable")
                    stage_info = response.json().get("ingest_phases", {})
                    ensure(
                        stage_info.get("total", {}).get("samples") == len(SIZES),
                        "unexpected ingest phase sample count",
                    )
        finally:
            stop(api)
            if created:
                sh("docker", "rm", "-f", container, timeout=20)
    ms = [item["duration_ms"] for item in readings]
    summary = {
        "scope": "serial_synthetic_text_ingest_shared_existing_live_qwen_disposable_pg17",
        "production_slo_proven": False,
        "same_as_production_request_mix": False,
        "model": "Qwen3-Embedding-4B",
        "observations": len(readings),
        "http_errors": sum(x["http_status"] >= 400 for x in readings),
        "p50_request_ms": percentile(ms, 0.5),
        "p95_request_ms": percentile(ms, 0.95),
        "max_request_ms": max(ms),
        "min_chunks": min(x["chunks"] for x in readings),
        "median_chunks": percentile([x["chunks"] for x in readings], 0.5),
        "max_chunks": max(x["chunks"] for x in readings),
        "phase_readiness": stage_info,
        "reference_target_ingest_p95_ms": 10000,
        "scheduler_restored": True,
        "production_DB_touched": False,
        "model_process_started": False,
        "disposable_DB_removed": True,
    }
    print("DP_QWEN_STAGE_RESULT=" + json.dumps(summary, sort_keys=True), flush=True)


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        # Do not leak an environment variable, database DSN or source content.
        print(
            json.dumps(
                {
                    "stage": "failed_closed",
                    "exception_type": type(exc).__name__,
                    "reason": str(exc) if isinstance(exc, RuntimeError) else "<redacted>",
                },
                sort_keys=True,
            ),
            flush=True,
        )
        raise SystemExit(2)
