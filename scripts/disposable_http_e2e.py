"""Isolated real HTTP + pgvector acceptance; never touches production data/models."""

from __future__ import annotations
import json
import math
import os
import secrets
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import httpx
from arvectum_data_client import DataPlatformClient
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parent.parent
BASE = "7eb86bd3da350ef3318790ce07b6a28aadac267e"
LABEL = "arvectum.dp.disposable_http_e2e"
SERVER = """
import os, uvicorn, time
import importlib; source=importlib.import_module("arvectum_data.api.app")
from arvectum_data.api.app import create_app
from arvectum_data.api.config import Settings
settings=Settings(_env_file=None, environment="test", deployment_mode="local-private",
 database_url=os.environ["E2E_DB"], internal_api_key=os.environ["E2E_KEY"],
 consumer_api_keys={"growth-agent":os.environ["E2E_CONSUMER"]},
 embedding_provider="hashing", embedding_model="e2e-hash-v1", embedding_dimension=64,
 cross_encoder_provider="disabled", reasoning_policy="disabled", vision_policy="disabled",
 embedding_retry_max_attempts=1, embedding_reuse_cache_entries=64,
 async_ingest_enabled=True, async_ingest_max_bytes=1000000)
app=create_app(settings)
if os.getenv("E2E_FAIL") == "1":
 old=app.state.platform_service.embedding_provider
 class Failed:
  provider_name=old.provider_name
  model_name=old.model_name
  dimension=old.dimension
  def embed_texts(self, texts): raise RuntimeError("synthetic provider outage")
  def embed_query(self, query): return old.embed_query(query)
 app.state.platform_service.embedding_provider=Failed()
if os.getenv("E2E_SLOW") == "1":
 old=app.state.platform_service.embedding_provider
 class Slow:
  provider_name=old.provider_name
  model_name=old.model_name
  dimension=old.dimension
  def embed_texts(self, texts):
   time.sleep(.04)
   return old.embed_texts(texts)
  def embed_query(self, query): return old.embed_query(query)
 app.state.platform_service.embedding_provider=Slow()
print("E2E_SOURCE="+str(source.__file__), flush=True)
uvicorn.run(app,host="127.0.0.1",port=int(os.environ["E2E_PORT"]),log_level="error")
"""


# A real child PID, deliberately stopped only in the disposable DB test.
# Its mock inference sleeps until the parent sends SIGTERM; no live model used.
KILLABLE_WORKER = """
import os, time
from arvectum_data.api.config import Settings
from arvectum_data.api.service import DataPlatformService
from arvectum_data.api.ingest_worker import run_one
service=DataPlatformService(Settings(_env_file=None,environment='test',
 database_url=os.environ['E2E_DB'],embedding_provider='hashing',
 embedding_model='e2e-hash-v1',embedding_dimension=64,
 cross_encoder_provider='disabled',reasoning_policy='disabled',
 vision_policy='disabled',async_ingest_enabled=True))
original=service.embedding_provider
class Slow:
 provider_name=original.provider_name
 model_name=original.model_name
 dimension=original.dimension
 def embed_texts(self,texts):
  time.sleep(20)
  return original.embed_texts(texts)
service.embedding_provider=Slow()
run_one(service)
"""


def sh(*cmd, timeout=60):
    return subprocess.run(
        cmd, capture_output=True, text=True, check=True, timeout=timeout
    ).stdout.strip()


def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ok(value, reason):
    if not value:
        raise AssertionError(reason)


def req(client, method, url, expected=200, **kw):
    r = client.request(method, url, **kw)
    ok(r.status_code == expected, f"{method} {url}: {r.status_code}: {r.text[:350]}")
    return r.json()


def stop(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=4)


def start(env, root, path):
    e = dict(env, PYTHONPATH=str(root / "src"))
    with path.open("w") as out:
        p = subprocess.Popen(
            [sys.executable, "-c", SERVER], cwd=root, env=e, stdout=out, stderr=subprocess.STDOUT
        )
    with httpx.Client(base_url=f"http://127.0.0.1:{e['E2E_PORT']}", timeout=4) as c:
        try:
            for _ in range(90):
                if p.poll() is not None:
                    raise AssertionError("API exited: " + path.read_text()[-1200:])
                try:
                    if c.get("/health").status_code == 200:
                        ok(str(root) in path.read_text(), "wrong runtime source")
                        return p
                except (httpx.ConnectError, httpx.ReadTimeout):
                    pass
                time.sleep(0.2)
            raise AssertionError("API did not start")
        except BaseException:
            stop(p)
            raise


def main():
    ok(not (ROOT / ".env").exists(), "refusing repository containing .env")
    ok(sh("git", "-C", str(ROOT), "rev-parse", "--is-inside-work-tree") == "true", "no worktree")
    uid = uuid.uuid4().hex[:10]
    name = f"dp-disposable-e2e-{uid}"
    user = f"e2e_{uid}"
    password = secrets.token_urlsafe(18)
    dbport = port()
    apiport = port()
    ok(dbport != apiport, "port collision")
    dsn = f"postgresql+psycopg://{user}:{password}@127.0.0.1:{dbport}/{user}"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ARVECTUM_DATA_", "E2E_"))}
    env.update(
        E2E_DB=dsn,
        E2E_KEY=secrets.token_urlsafe(24),
        E2E_CONSUMER=secrets.token_urlsafe(24),
        E2E_PORT=str(apiport),
    )
    h = {"X-Arvectum-Key": env["E2E_KEY"]}
    ch = dict(
        h, **{"X-Arvectum-Consumer": "growth-agent", "X-Arvectum-Consumer-Key": env["E2E_CONSUMER"]}
    )
    p = None
    created = False
    checks = []
    lat = []
    with tempfile.TemporaryDirectory(prefix="dp-http-e2e-") as temp:
        wd = Path(temp)
        try:
            sh(
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "--label",
                f"{LABEL}=true",
                "--memory",
                "384m",
                "--cpus",
                "1",
                "-p",
                f"127.0.0.1:{dbport}:5432",
                "-e",
                f"POSTGRES_USER={user}",
                "-e",
                f"POSTGRES_PASSWORD={password}",
                "-e",
                f"POSTGRES_DB={user}",
                "--health-cmd",
                f"pg_isready -U {user} -d {user}",
                "--health-interval",
                "1s",
                "--health-timeout",
                "1s",
                "--health-retries",
                "30",
                "pgvector/pgvector:pg17",
                timeout=100,
            )
            created = True
            for _ in range(80):
                if sh("docker", "inspect", "-f", "{{.State.Health.Status}}", name) == "healthy":
                    break
                time.sleep(0.25)
            else:
                raise AssertionError("disposable PostgreSQL health failure")
            engine = create_engine(dsn)
            try:
                with engine.connect() as c:
                    ok(
                        tuple(c.execute(text("select current_database(),current_user")).one())
                        == (user, user),
                        "disposable DB identity mismatch",
                    )
            finally:
                engine.dispose()
            previous = os.environ.get("ARVECTUM_DATA_DATABASE_URL")
            try:
                os.environ["ARVECTUM_DATA_DATABASE_URL"] = dsn
                command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
            finally:
                if previous is None:
                    os.environ.pop("ARVECTUM_DATA_DATABASE_URL", None)
                else:
                    os.environ["ARVECTUM_DATA_DATABASE_URL"] = previous
            checks.append("PG17 identity and Alembic migration")
            p = start(env, ROOT, wd / "first.log")
            base_url = f"http://127.0.0.1:{apiport}"
            normal = f"e2e:docs:{uid}"
            restricted = f"e2e:restricted:{uid}"
            with httpx.Client(base_url=base_url, timeout=30) as c:
                ok(req(c, "GET", "/health")["status"] == "ok", "health")
                ok(
                    req(c, "GET", "/v1/contract", headers=h)["version"].startswith("1."),
                    "contract 1.x",
                )
                req(c, "GET", "/v1/status", expected=401)
                checks.append("real HTTP startup/auth/consumer contract")
                for cid, acl in (
                    (normal, None),
                    (restricted, {"allowed_consumers": ["growth-agent"]}),
                ):
                    data = {
                        "collection_id": cid,
                        "owner": "synthetic-test",
                        "name": "Isolated E2E",
                        "default_language": "russian",
                    }
                    if acl:
                        data["access_policy"] = acl
                    req(c, "POST", "/v1/collections", headers=h, json=data)
                # Durable async intake: 202 is only a committed queued receipt.
                async_payload = ("Асинхронный тестовый кабель на отдельном объекте. " * 35).encode()
                enqueue = {
                    "collection_id": normal,
                    "canonical_uri": f"synthetic://{uid}/async-background",
                }
                idem_h = dict(h, **{"Idempotency-Key": f"synthetic-{uid}-async-main"})
                queued = req(
                    c,
                    "POST",
                    "/v1/ingest/jobs",
                    expected=202,
                    headers=idem_h,
                    data=enqueue,
                    files={"file": ("queued.txt", async_payload, "text/plain")},
                )
                ok(
                    queued["status"] == "queued"
                    and queued["attempts"] == 0
                    and queued["result"] is None,
                    "202 inaccurately claimed an indexed source",
                )
                receipt_url = f"/v1/ingest/jobs/{queued['job_id']}?collection_id={normal}"
                original = req(c, "GET", receipt_url, headers=h)
                ok(original["status"] == "queued", "queued job not durable")
                retry = req(
                    c,
                    "POST",
                    "/v1/ingest/jobs",
                    expected=202,
                    headers=idem_h,
                    data=enqueue,
                    files={"file": ("queued.txt", async_payload, "text/plain")},
                )
                ok(retry["job_id"] == queued["job_id"], "idempotency created duplicate job")
                req(
                    c,
                    "POST",
                    "/v1/ingest/jobs",
                    expected=409,
                    headers=idem_h,
                    data=enqueue,
                    files={"file": ("queued.txt", b"different content", "text/plain")},
                )
                req(
                    c,
                    "GET",
                    f"/v1/ingest/jobs/{queued['job_id']}?collection_id={restricted}",
                    headers=h,
                    expected=404,
                )
                req(c, "GET", receipt_url, expected=401)
                req(
                    c,
                    "POST",
                    "/v1/ingest/jobs",
                    expected=401,
                    data=enqueue,
                    headers={"Idempotency-Key": "synthetic-unauthorized"},
                    files={"file": ("queued.txt", async_payload, "text/plain")},
                )
                cancelled = req(
                    c,
                    "POST",
                    "/v1/ingest/jobs",
                    expected=202,
                    headers=dict(h, **{"Idempotency-Key": f"synthetic-{uid}-cancel"}),
                    data=enqueue,
                    files={"file": ("queued-cancel.txt", b"cancel-only-not-indexed", "text/plain")},
                )
                cancelled_url = f"/v1/ingest/jobs/{cancelled['job_id']}?collection_id={normal}"
                cancel_ack = req(c, "DELETE", cancelled_url, headers=h)
                ok(cancel_ack["status"] == "cancelled", "pending job cancellation failed")
                # Execute a real job via a separately constructed, manually invoked worker;
                # no production or background daemon automatically starts from HTTP.
                from arvectum_data.api.config import Settings
                from arvectum_data.api.service import DataPlatformService
                from arvectum_data.api.ingest_worker import run_one

                worker_service = DataPlatformService(
                    Settings(
                        _env_file=None,
                        environment="test",
                        database_url=dsn,
                        embedding_provider="hashing",
                        embedding_model="e2e-hash-v1",
                        embedding_dimension=64,
                        cross_encoder_provider="disabled",
                        reasoning_policy="disabled",
                        vision_policy="disabled",
                        async_ingest_enabled=True,
                        async_ingest_max_bytes=1000000,
                    )
                )
                ok(run_one(worker_service), "queued worker did not claim job")
                done = req(c, "GET", receipt_url, headers=h)
                ok(
                    done["status"] == "completed" and done["attempts"] == 1,
                    "completed worker state not durable",
                )
                ok(
                    done["result"]["chunks"] > 0 and bool(done["result"]["document_id"]),
                    "completed worker did not report indexed document",
                )
                ok(not run_one(worker_service), "cancelled job was claimable")
                from arvectum_data.storage.postgres import AsyncIngestJobRow

                with worker_service._require_factory()() as sess:
                    persisted = sess.get(AsyncIngestJobRow, queued["job_id"])
                    cancelled_row = sess.get(AsyncIngestJobRow, cancelled["job_id"])
                    ok(
                        persisted.content is None and cancelled_row.content is None,
                        "terminal jobs retained raw uploaded source payload",
                    )
                found = req(
                    c,
                    "POST",
                    "/v1/search",
                    headers=h,
                    json={
                        "query": "Асинхронный тестовый кабель",
                        "collections": [normal],
                        "mode": "lexical",
                    },
                )["hits"]
                ok(
                    any(
                        any(
                            ev["canonical_uri"] == enqueue["canonical_uri"]
                            for ev in hit.get("evidence", [])
                        )
                        for hit in found
                    ),
                    "completed background source not searchable with correct provenance",
                )
                report = req(c, "GET", "/v1/support/ingest-jobs", headers=h)
                ok(
                    report["backlog_active_count_global"] == 0,
                    "completed/cancelled async jobs leaked into queue backlog",
                )
                ok(
                    report["started_samples"] >= 1 and report["queue_wait_p95_ms"] >= 0,
                    "background first-start queue wait SLI not aggregated",
                )
                ok(
                    report["completed_samples"] >= 1 and report["completed_p95_ms"] >= 0,
                    "background completion SLI not aggregated",
                )
                ok(
                    report["terminal_error_rate"] == 0,
                    "nonfailed asynchronous jobs reported as failed",
                )
                ok(
                    not report["sufficient_completion_samples"],
                    "sparse async completion samples incorrectly declared sufficient",
                )
                ok(
                    "canonical_uri" not in json.dumps(report) and "content" not in report,
                    "background read-only support leaked source metadata",
                )
                req(c, "GET", "/v1/support/ingest-jobs", expected=401)
                checks.append("source-free separate async backlog/completion SLI")
                checks.append("durable async intake/idempotency/ACL/cancel/manual worker/search")
                from arvectum_data.api.ingest_worker import claim_one, complete_one
                from sqlalchemy import update
                from datetime import datetime, timedelta, UTC
                from arvectum_data.indexing import EmbeddingServerUnavailableError

                # A running job is deliberately NOT cancellable: current ingest is atomic.
                crash_h = dict(h, **{"Idempotency-Key": f"synthetic-{uid}-crash"})
                crashed = req(
                    c,
                    "POST",
                    "/v1/ingest/jobs",
                    expected=202,
                    headers=crash_h,
                    data={"collection_id": normal},
                    files={
                        "file": ("crash.txt", b"synthetic recovered worker " * 50, "text/plain")
                    },
                )
                with ThreadPoolExecutor(max_workers=2) as pool:
                    claims = list(pool.map(lambda _: claim_one(worker_service), range(2)))
                active_claims = [item for item in claims if item is not None]
                ok(len(active_claims) == 1, "SKIP LOCKED allowed two workers to claim one job")
                old_claim = active_claims[0]
                ok(old_claim["job_id"] == crashed["job_id"], "crash probe claimed wrong job")
                crash_url = f"/v1/ingest/jobs/{crashed['job_id']}?collection_id={normal}"
                req(c, "DELETE", crash_url, headers=h, expected=409)
                with worker_service._require_factory()() as sess:
                    sess.execute(
                        update(AsyncIngestJobRow)
                        .where(AsyncIngestJobRow.job_id == crashed["job_id"])
                        .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
                    )
                    sess.commit()
                ok(run_one(worker_service), "expired lease did not recover after crash")
                recovered = req(c, "GET", crash_url, headers=h)
                ok(
                    recovered["status"] == "completed" and recovered["attempts"] == 2,
                    "lease replay did not complete after simulated worker crash",
                )
                complete_one(worker_service, old_claim, failure=RuntimeError("stale worker"))
                ok(
                    req(c, "GET", crash_url, headers=h)["status"] == "completed",
                    "stale lease overwrote completed outcome",
                )
                checks.append("worker crash/expired lease replay/stale token blocked")
                # A REAL child process is SIGTERM'd while embedding (not merely
                # a synthetic lease manipulation). Only this owned test PID dies.
                killed_h = dict(h, **{"Idempotency-Key": f"synthetic-{uid}-pid-kill"})
                killed = req(
                    c,
                    "POST",
                    "/v1/ingest/jobs",
                    expected=202,
                    headers=killed_h,
                    data={
                        "collection_id": normal,
                        "canonical_uri": f"synthetic://{uid}/killed-worker",
                    },
                    files={
                        "file": (
                            "pid-kill.txt",
                            b"synthetic killable pending source " * 48,
                            "text/plain",
                        )
                    },
                )
                kill_url = f"/v1/ingest/jobs/{killed['job_id']}?collection_id={normal}"
                fault_worker = subprocess.Popen(
                    [sys.executable, "-c", KILLABLE_WORKER],
                    cwd=ROOT,
                    env=dict(env, PYTHONPATH=str(ROOT / "src")),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                try:
                    for _ in range(120):
                        if fault_worker.poll() is not None:
                            raise AssertionError("isolated killable worker quit unexpectedly")
                        state = req(c, "GET", kill_url, headers=h)
                        if state["status"] == "running":
                            break
                        time.sleep(0.05)
                    else:
                        raise AssertionError("isolated killable worker did not claim job")
                    fault_worker.terminate()  # Own disposable child PID only.
                    fault_worker.wait(timeout=5)
                    state = req(c, "GET", kill_url, headers=h)
                    ok(
                        state["status"] == "running" and state["attempts"] == 1,
                        "SIGTERM failed to leave a durable leased job",
                    )
                finally:
                    stop(fault_worker)
                with worker_service._require_factory()() as sess:
                    sess.execute(
                        update(AsyncIngestJobRow)
                        .where(AsyncIngestJobRow.job_id == killed["job_id"])
                        .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
                    )
                    sess.commit()
                ok(run_one(worker_service), "actual SIGTERM worker lease was not recovered")
                state = req(c, "GET", kill_url, headers=h)
                ok(
                    state["status"] == "completed" and state["attempts"] == 2,
                    "actual SIGTERM recovery failed",
                )
                with worker_service._require_factory()() as sess:
                    row = sess.get(AsyncIngestJobRow, killed["job_id"])
                    ok(row.content is None, "completed worker retained sensitive upload")
                checks.append("real isolated worker SIGTERM, lease expiry, durable replay")

                # The first failed inference must release the job for retry, not fake 202 completion.
                retry_h = dict(h, **{"Idempotency-Key": f"synthetic-{uid}-retry"})
                failed_job = req(
                    c,
                    "POST",
                    "/v1/ingest/jobs",
                    expected=202,
                    headers=retry_h,
                    data={"collection_id": normal},
                    files={"file": ("retry.txt", b"unique synthetic retry " * 51, "text/plain")},
                )
                retry_url = f"/v1/ingest/jobs/{failed_job['job_id']}?collection_id={normal}"
                old_provider = worker_service.embedding_provider

                class TransientOutage:
                    provider_name = old_provider.provider_name
                    model_name = old_provider.model_name
                    dimension = old_provider.dimension

                    def embed_texts(self, _texts):
                        raise EmbeddingServerUnavailableError("synthetic outage")

                worker_service.embedding_provider = TransientOutage()
                try:
                    ok(run_one(worker_service), "failed provider job not claimed")
                finally:
                    worker_service.embedding_provider = old_provider
                state = req(c, "GET", retry_url, headers=h)
                ok(
                    state["status"] == "queued" and state["attempts"] == 1,
                    "failed inference not requeued for bounded retry",
                )
                with worker_service._require_factory()() as sess:
                    sess.execute(
                        update(AsyncIngestJobRow)
                        .where(AsyncIngestJobRow.job_id == failed_job["job_id"])
                        .values(run_after=datetime.now(UTC) - timedelta(seconds=1))
                    )
                    sess.commit()
                ok(run_one(worker_service), "retry did not pick up pending job")
                state = req(c, "GET", retry_url, headers=h)
                ok(
                    state["status"] == "completed" and state["attempts"] == 2,
                    "recovered retry not committed exactly once",
                )
                checks.append("failed model retry and restoration of queue worker")
                # Bounded collection admission, including read-only idempotency replay
                # when the queue has reached its active-job limit.
                from arvectum_data.api.async_ingest import IngestJobQueueFull

                tight = DataPlatformService(
                    Settings(
                        _env_file=None,
                        environment="test",
                        database_url=dsn,
                        embedding_provider="hashing",
                        embedding_model="e2e-hash-v1",
                        embedding_dimension=64,
                        cross_encoder_provider="disabled",
                        async_ingest_enabled=True,
                        async_ingest_max_active_jobs=1,
                        async_ingest_max_queued_bytes=2000,
                    )
                )
                first_capacity = tight.enqueue_ingest_document(
                    collection_id=normal,
                    filename="capacity.txt",
                    content=b"bounded-queued-data" * 15,
                    idempotency_key=f"synthetic-{uid}-capacity-1",
                )
                same_capacity = tight.enqueue_ingest_document(
                    collection_id=normal,
                    filename="capacity.txt",
                    content=b"bounded-queued-data" * 15,
                    idempotency_key=f"synthetic-{uid}-capacity-1",
                )
                ok(
                    first_capacity["job_id"] == same_capacity["job_id"],
                    "idempotent replay blocked by full queue",
                )
                try:
                    tight.enqueue_ingest_document(
                        collection_id=normal,
                        filename="capacity-2.txt",
                        content=b"another synthetic document",
                        idempotency_key=f"synthetic-{uid}-capacity-2",
                    )
                    raise AssertionError("second job bypassed active capacity")
                except IngestJobQueueFull:
                    pass
                tight.cancel_queued_ingest_job(
                    collection_id=normal, job_id=first_capacity["job_id"]
                )
                # Deterministically invalid input is dead-lettered and raw upload
                # removed. No unbounded retries or fake searchable completion.
                invalid_job = tight.enqueue_ingest_document(
                    collection_id=normal,
                    filename="invalid.txt",
                    content=b"synthetic invalid worker content " * 18,
                    idempotency_key=f"synthetic-{uid}-invalid-1",
                )

                class InvalidProvider:
                    provider_name = old_provider.provider_name
                    model_name = old_provider.model_name
                    dimension = old_provider.dimension

                    def embed_texts(self, _texts):
                        raise ValueError("synthetic invalid inference")

                worker_service.embedding_provider = InvalidProvider()
                try:
                    ok(run_one(worker_service), "invalid job not claimed")
                finally:
                    worker_service.embedding_provider = old_provider
                invalid_url = f"/v1/ingest/jobs/{invalid_job['job_id']}?collection_id={normal}"
                terminal_invalid = req(c, "GET", invalid_url, headers=h)
                ok(
                    terminal_invalid["status"] == "dead_letter"
                    and terminal_invalid["attempts"] == 1
                    and terminal_invalid["result"] is None,
                    "invalid inference did not terminate fail-closed",
                )
                with worker_service._require_factory()() as sess:
                    row = sess.get(AsyncIngestJobRow, invalid_job["job_id"])
                    ok(
                        row.content is None and row.error_class == "ValueError",
                        "dead-letter payload was retained or error leaked details",
                    )
                summary = req(c, "GET", "/v1/support/ingest-jobs", headers=h)
                ok(
                    summary["terminal_dead_letter_count"] >= 1
                    and summary["terminal_error_rate"] > 0,
                    "terminal error rate did not surface unsuccessful job",
                )
                # One globally bounded backlog must not grow unbounded as
                # collection count grows, even with local quotas available.
                global_tight = DataPlatformService(
                    Settings(
                        _env_file=None,
                        environment="test",
                        database_url=dsn,
                        embedding_provider="hashing",
                        embedding_model="e2e-hash-v1",
                        embedding_dimension=64,
                        cross_encoder_provider="disabled",
                        async_ingest_enabled=True,
                        async_ingest_max_global_jobs=1,
                    )
                )
                a_global = global_tight.enqueue_ingest_document(
                    collection_id=normal,
                    filename="global-a.txt",
                    content=b"synthetic bounded global a" * 12,
                    idempotency_key=f"synthetic-{uid}-global-a",
                )
                try:
                    global_tight.enqueue_ingest_document(
                        collection_id=restricted,
                        filename="global-b.txt",
                        content=b"synthetic bounded global b" * 12,
                        idempotency_key=f"synthetic-{uid}-global-b",
                    )
                    raise AssertionError("global queue limit ignored across collections")
                except IngestJobQueueFull:
                    pass
                global_tight.cancel_queued_ingest_job(
                    collection_id=normal, job_id=a_global["job_id"]
                )
                checks.append("bounded queue admission and dead-letter failed inference")

                # A second pending job remains durable and unindexed until worker starts,
                # even if the HTTP service process is deliberately restarted below.
                restart_h = dict(h, **{"Idempotency-Key": f"synthetic-{uid}-restart"})
                pending_on_restart = req(
                    c,
                    "POST",
                    "/v1/ingest/jobs",
                    expected=202,
                    headers=restart_h,
                    data={"collection_id": normal},
                    files={
                        "file": (
                            "after-restart.txt",
                            b"queue persisted across restart " * 55,
                            "text/plain",
                        )
                    },
                )
                pending_restart_url = (
                    f"/v1/ingest/jobs/{pending_on_restart['job_id']}?collection_id={normal}"
                )
                doc = ("Силовой кабель для промышленного объекта. " * 25).encode()

                def ingest(uri, collection, payload=doc):
                    return req(
                        c,
                        "POST",
                        "/v1/ingest/document",
                        headers=h,
                        data={
                            "collection_id": collection,
                            "canonical_uri": uri,
                            "pre_chunked": "true",
                        },
                        files={"file": ("synthetic.txt", payload, "text/plain")},
                    )

                uri = f"synthetic://{uid}/base"
                a = ingest(uri, normal)
                b = ingest(uri, normal)
                ok(
                    a["resource_id"] == b["resource_id"] and b["embeddings_written"] == 0,
                    "idempotency",
                )
                reused_uri = f"synthetic://{uid}/reuse"
                reused = ingest(reused_uri, normal)
                ok(reused["chunks"] == a["chunks"], "cached text chunk count changed")
                ok(
                    reused["embeddings_written"] == reused["chunks"],
                    "new source did not persist its own vectors",
                )
                ok(
                    reused["embedding_attempts"] == 0,
                    "identical same-collection chunk did not reuse committed vector",
                )
                isolated = ingest(f"synthetic://{uid}/protected", restricted)
                ok(
                    isolated["embedding_attempts"] > 0,
                    "embedding cache leaked across collection boundary",
                )
                checks.append("opt-in cached embedding reuse, strict collection isolation")
                checks.append("ingest/chunk/index/idempotency")
                for mode in ("lexical", "vector", "hybrid"):
                    hits = req(
                        c,
                        "POST",
                        "/v1/search",
                        headers=h,
                        json={"query": "силовой кабель", "collections": [normal], "mode": mode},
                    )["hits"]
                    ok(
                        bool(hits) and hits[0]["evidence"][0]["canonical_uri"] in {uri, reused_uri},
                        f"{mode} provenance",
                    )
                req(
                    c,
                    "POST",
                    "/v1/search",
                    headers=h,
                    expected=403,
                    json={"query": "кабель", "collections": [restricted]},
                )
                fed = req(
                    c,
                    "POST",
                    "/v1/search",
                    headers=ch,
                    json={"query": "кабель", "collections": [normal, restricted]},
                )
                ok(
                    {normal, restricted} <= {x["metadata"]["collection_id"] for x in fed["hits"]},
                    "consumer ACL",
                )
                checks.append("lexical/vector/hybrid, provenance, consumer ACL")
                with DataPlatformClient(
                    base_url=base_url,
                    api_key=env["E2E_KEY"],
                    consumer="growth-agent",
                    consumer_key=env["E2E_CONSUMER"],
                ) as sdk:
                    sdk.require_contract(major=1)
                    sdk_hits = sdk.search(
                        query="кабель", collections=[normal, restricted], limit=10
                    )
                    ok(len(sdk_hits) >= 2, "released Python SDK returned no federated evidence")
                checks.append("real Python consumer SDK against isolated HTTP server")
                job = req(c, "POST", "/v1/index/rebuild", headers=h, json={"collection_id": normal})
                same = req(
                    c, "POST", "/v1/index/rebuild", headers=h, json={"collection_id": normal}
                )
                stats = req(c, "GET", f"/v1/collections/{normal}/stats", headers=h)
                ok(
                    job["status"] == "completed"
                    and job["run_id"] == same["run_id"]
                    and stats["active_index_revision"] == job["revision"],
                    "index revision",
                )
                checks.append("atomic index revision and idempotent rebuild")
                for i in range(20):
                    t = time.perf_counter()
                    ingest(
                        f"synthetic://{uid}/timed-{i}",
                        normal,
                        (f"Синтетический кабель измерение {i}. " * 15).encode(),
                    )
                    lat.append(1000 * (time.perf_counter() - t))

                def concurrent(i):
                    with httpx.Client(base_url=base_url, timeout=30) as other:
                        return req(
                            other,
                            "POST",
                            "/v1/ingest/document",
                            headers=h,
                            data={
                                "collection_id": normal,
                                "canonical_uri": f"synthetic://{uid}/concurrent-{i}",
                                "pre_chunked": "true",
                            },
                            files={
                                "file": (
                                    "concurrent.txt",
                                    (f"Кабель {i} " * 30).encode(),
                                    "text/plain",
                                )
                            },
                        )

                with ThreadPoolExecutor(max_workers=3) as pool:
                    concurrent_results = list(pool.map(concurrent, range(3)))
                ok(len({x["resource_id"] for x in concurrent_results}) == 3, "concurrency")
                checks.append("20 synthetic hashing observations + 3 concurrent ingest")
                for section_count, expected_cohort in (
                    (80, "four_to_eight"),
                    (380, "seventeen_plus"),
                ):
                    # Unique sections avoid chunk-hash deduplication of periodic text.
                    source = " ".join(
                        f"Синтетический номер {i:05d}. Контроль изоляции и монтаж кабеля."
                        for i in range(section_count)
                    ).encode()
                    ingested = req(
                        c,
                        "POST",
                        "/v1/ingest/document",
                        headers=h,
                        data={
                            "collection_id": normal,
                            "canonical_uri": f"synthetic://{uid}/cohort-{section_count}",
                        },
                        files={"file": ("cohort.txt", source, "text/plain")},
                    )
                    if expected_cohort == "four_to_eight":
                        ok(4 <= ingested["chunks"] <= 8, "medium test chunk count drift")
                    else:
                        ok(ingested["chunks"] >= 17, "large test chunk count drift")
                phase_readiness = req(c, "GET", "/v1/support/readiness", headers=h)
                traces = phase_readiness["ingest_phases"]
                ok(traces["content_included"] is False, "ingest trace leaked source content")
                ok(traces["total"]["samples"] >= 20, "missing ingest phase observations")
                ok(traces["total"]["sufficient_samples"], "insufficient ingest phase window")
                ok(traces["total"]["phase_p95_ms"]["embedding"] >= 1, "missing embedding span")
                ok(traces["total"]["phase_p95_ms"]["lookup"] >= 1, "missing DB lookup span")
                ok(traces["total"]["phase_p95_ms"]["persist"] >= 1, "missing SQL commit span")
                ok(f"synthetic://{uid}" not in json.dumps(traces), "source identity leaked")
                groups = traces["by_chunk_count"]
                for cohort in ("one_to_three", "four_to_eight", "seventeen_plus"):
                    ok(groups[cohort]["samples"] > 0, f"missing {cohort} phase cohort")
                ok(
                    sum(row["samples"] for row in groups.values()) == traces["total"]["samples"],
                    "chunk-count cohorts do not partition all HTTP observations",
                )
                ok(
                    groups["four_to_eight"]["sufficient_samples"] is False,
                    "sparse medium cohort incorrectly called sufficient",
                )
                ok(
                    groups["seventeen_plus"]["sufficient_samples"] is False,
                    "sparse large cohort incorrectly called sufficient",
                )
                ok(
                    traces["total"]["window_error_rate"] == 0,
                    "all-success cohort has nonzero error rate",
                )
                req(c, "GET", "/v1/support/readiness", expected=401)
                checks.append(
                    "numeric-only ingest phases, size and chunk cohorts, authenticated readiness"
                )
            stop(p)
            p = start(env, ROOT, wd / "restart.log")
            with httpx.Client(base_url=base_url, timeout=15) as c:
                persisted = req(c, "GET", pending_restart_url, headers=h)
                ok(
                    persisted["status"] == "queued" and persisted["attempts"] == 0,
                    "HTTP restart lost the unprocessed background job",
                )
                ok(run_one(worker_service), "worker could not process persisted job")
                saved = req(c, "GET", pending_restart_url, headers=h)
                ok(
                    saved["status"] == "completed" and saved["attempts"] == 1,
                    "restarted process did not observe committed job result",
                )
                ok(
                    bool(
                        req(
                            c,
                            "POST",
                            "/v1/search",
                            headers=h,
                            json={"query": "кабель", "collections": [normal]},
                        )["hits"]
                    ),
                    "restart persistence",
                )
            checks.append("shutdown/restart persistence")
            checks.append("queued job survives HTTP process restart")
            stop(p)
            p = start(dict(env, E2E_FAIL="1"), ROOT, wd / "failure.log")
            with httpx.Client(base_url=base_url, timeout=15) as c:
                req(
                    c,
                    "POST",
                    "/v1/ingest/document",
                    headers=h,
                    expected=500,
                    data={
                        "collection_id": normal,
                        "canonical_uri": f"synthetic://{uid}/failure",
                        "pre_chunked": "true",
                    },
                    files={
                        "file": ("failure.txt", b"synthetic embedding error " * 20, "text/plain")
                    },
                )
            stop(p)
            p = start(env, ROOT, wd / "recovery.log")
            with httpx.Client(base_url=base_url, timeout=15) as c:
                result = req(
                    c,
                    "POST",
                    "/v1/ingest/document",
                    headers=h,
                    data={
                        "collection_id": normal,
                        "canonical_uri": f"synthetic://{uid}/failure",
                        "pre_chunked": "true",
                    },
                    files={
                        "file": ("failure.txt", b"synthetic embedding error " * 20, "text/plain")
                    },
                )
                ok(
                    result["embeddings_written"] == result["chunks"],
                    "failed inference partial data",
                )
            checks.append("provider failure fail-closed and recovery")
            stop(p)
            p = start(dict(env, E2E_SLOW="1"), ROOT, wd / "slow-provider.log")
            with httpx.Client(base_url=base_url, timeout=15) as c:
                slow_payload = b"synthetic local inference " * 25
                first_slow = req(
                    c,
                    "POST",
                    "/v1/ingest/document",
                    headers=h,
                    data={
                        "collection_id": normal,
                        "canonical_uri": f"synthetic://{uid}/slow-inference",
                        "pre_chunked": "true",
                    },
                    files={"file": ("slow.txt", slow_payload, "text/plain")},
                )
                ok(first_slow["embedding_attempts"] >= 1, "simulated provider not invoked")
                timings = req(c, "GET", "/v1/support/readiness", headers=h)
                phase = timings["ingest_phases"]["total"]
                ok(phase["samples"] >= 1, "slow ingest metrics absent")
                ok(
                    phase["phase_p95_ms"]["embedding"] >= 40,
                    "simulated model wait was not attributed to embedding",
                )
                ok(
                    phase["request_p95_ms"] >= 40,
                    "simulated model wait was not counted in request wall time",
                )
                second_slow = req(
                    c,
                    "POST",
                    "/v1/ingest/document",
                    headers=h,
                    data={
                        "collection_id": normal,
                        "canonical_uri": f"synthetic://{uid}/slow-reuse",
                        "pre_chunked": "true",
                    },
                    files={"file": ("slow.txt", slow_payload, "text/plain")},
                )
                ok(
                    second_slow["embedding_attempts"] == 0,
                    "same-collection cache did not skip simulated 40ms inference",
                )
                ok(
                    second_slow["embeddings_written"] == second_slow["chunks"],
                    "cached vector not persisted for new source",
                )
            checks.append("40ms isolated inference delay attributed to embedding phase")
            checks.append("opt-in cache skips slow provider after committed identical text")
            stop(p)
            baseline = wd / "baseline"
            baseline.mkdir()
            archive = wd / "parent.tar"
            with archive.open("wb") as out:
                subprocess.run(
                    ["git", "-C", str(ROOT), "archive", "--format=tar", BASE],
                    stdout=out,
                    check=True,
                    timeout=30,
                )
            with tarfile.open(archive) as tar:
                tar.extractall(path=baseline, filter="data")
            p = start(env, baseline, wd / "rollback.log")
            with httpx.Client(base_url=base_url, timeout=15) as c:
                ok(
                    bool(
                        req(
                            c,
                            "POST",
                            "/v1/search",
                            headers=h,
                            json={"query": "кабель", "collections": [normal]},
                        )["hits"]
                    ),
                    "rollback lost data",
                )
            checks.append("PR #134 source rollback and persisted search")
            stop(p)
            p = start(env, ROOT, wd / "forward.log")
            with httpx.Client(base_url=base_url, timeout=15) as c:
                ok(
                    bool(
                        req(
                            c,
                            "POST",
                            "/v1/search",
                            headers=h,
                            json={"query": "кабель", "collections": [normal]},
                        )["hits"]
                    ),
                    "forward recovery",
                )
            checks.append("candidate forward recovery")
            # Schema rollback drills are destructive to async job rows; execute
            # ONLY after all synthetic job tests and ONLY on the owned PG17 DB.
            stop(p)
            previous = os.environ.get("ARVECTUM_DATA_DATABASE_URL")
            try:
                os.environ["ARVECTUM_DATA_DATABASE_URL"] = dsn
                check_engine = create_engine(dsn)
                try:
                    with check_engine.connect() as conn:
                        original_resource_count = conn.execute(
                            text("select count(*) from dp_resources")
                        ).scalar_one()
                        ok(original_resource_count > 0, "migration drill missing baseline data")
                        ok(
                            conn.execute(
                                text("select to_regclass('public.dp_async_ingest_jobs')")
                            ).scalar_one()
                            is not None,
                            "pre-rollback async table missing",
                        )
                    try:
                        command.downgrade(
                            Config(str(ROOT / "alembic.ini")),
                            "0013_invoice_provider_status",
                        )
                    except RuntimeError as exc:
                        ok(
                            "nonempty jobs" in str(exc),
                            "nonempty async queue downgrade failed for wrong reason",
                        )
                    else:
                        raise AssertionError("downgrade erased jobs without explicit drain")
                    with check_engine.begin() as conn:
                        ok(
                            conn.execute(
                                text("select count(*) from dp_async_ingest_jobs")
                            ).scalar_one()
                            > 0,
                            "refused downgrade unexpectedly cleared pending audit",
                        )
                        # Only on the owned, disposable DB after all job tests.
                        conn.execute(text("DELETE FROM dp_async_ingest_jobs"))
                    command.downgrade(
                        Config(str(ROOT / "alembic.ini")), "0013_invoice_provider_status"
                    )
                    with check_engine.connect() as conn:
                        ok(
                            conn.execute(
                                text("select to_regclass('public.dp_async_ingest_jobs')")
                            ).scalar_one()
                            is None,
                            "0014 downgrade left queue table",
                        )
                        ok(
                            conn.execute(text("select count(*) from dp_resources")).scalar_one()
                            == original_resource_count,
                            "0014 downgrade modified old indexed resources",
                        )
                    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
                    with check_engine.connect() as conn:
                        ok(
                            conn.execute(
                                text("select count(*) from dp_async_ingest_jobs")
                            ).scalar_one()
                            == 0,
                            "upgrade recovered deleted queue payload",
                        )
                        ok(
                            conn.execute(text("select count(*) from dp_resources")).scalar_one()
                            == original_resource_count,
                            "0014 re-upgrade lost indexed resources",
                        )
                finally:
                    check_engine.dispose()
            finally:
                if previous is None:
                    os.environ.pop("ARVECTUM_DATA_DATABASE_URL", None)
                else:
                    os.environ["ARVECTUM_DATA_DATABASE_URL"] = previous
            p = start(env, ROOT, wd / "post-migration-drill.log")
            with httpx.Client(base_url=base_url, timeout=15) as c:
                ok(
                    bool(
                        req(
                            c,
                            "POST",
                            "/v1/search",
                            headers=h,
                            json={"query": "кабель", "collections": [normal]},
                        )["hits"]
                    ),
                    "search failed after isolated migration rollback/re-upgrade",
                )
            checks.append("0014 downgrade/re-upgrade preserves pre-existing index; jobs drained")
            sorted_ms = sorted(lat)
            print(
                json.dumps(
                    {
                        "status": "PASS",
                        "head": sh("git", "-C", str(ROOT), "rev-parse", "HEAD"),
                        "checks": checks,
                        "synthetic_samples": len(lat),
                        "synthetic_hashing_p95_ms": round(
                            sorted_ms[math.ceil(len(lat) * 0.95) - 1], 2
                        ),
                        "production_slo": "NOT ASSESSED",
                        "db": "isolated PostgreSQL17 pgvector localhost",
                        "model": "hashing mock only",
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
        finally:
            stop(p)
            if created:
                label = sh(
                    "docker", "inspect", "-f", '{{index .Config.Labels "' + LABEL + '"}}', name
                )
                ok(label == "true", "refusing cleanup of unowned container")
                sh("docker", "rm", "-f", name, timeout=30)


if __name__ == "__main__":
    main()
