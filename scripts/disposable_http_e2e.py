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
 embedding_retry_max_attempts=1)
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
                ingest(f"synthetic://{uid}/protected", restricted)
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
                        bool(hits) and hits[0]["evidence"][0]["canonical_uri"] == uri,
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
                phase_readiness = req(c, "GET", "/v1/support/readiness", headers=h)
                traces = phase_readiness["ingest_phases"]
                ok(traces["content_included"] is False, "ingest trace leaked source content")
                ok(traces["total"]["samples"] >= 20, "missing ingest phase observations")
                ok(traces["total"]["sufficient_samples"], "insufficient ingest phase window")
                ok(traces["total"]["phase_p95_ms"]["embedding"] >= 1, "missing embedding span")
                ok(traces["total"]["phase_p95_ms"]["lookup"] >= 1, "missing DB lookup span")
                ok(traces["total"]["phase_p95_ms"]["persist"] >= 1, "missing SQL commit span")
                ok(f"synthetic://{uid}" not in json.dumps(traces), "source identity leaked")
                req(c, "GET", "/v1/support/readiness", expected=401)
                checks.append(
                    "numeric-only ingest phases, size cohorts, and authenticated readiness"
                )
            stop(p)
            p = start(env, ROOT, wd / "restart.log")
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
                    "restart persistence",
                )
            checks.append("shutdown/restart persistence")
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
                req(
                    c,
                    "POST",
                    "/v1/ingest/document",
                    headers=h,
                    data={
                        "collection_id": normal,
                        "canonical_uri": f"synthetic://{uid}/slow-inference",
                        "pre_chunked": "true",
                    },
                    files={"file": ("slow.txt", b"synthetic local inference " * 25, "text/plain")},
                )
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
            checks.append("40ms isolated inference delay attributed to embedding phase")
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
