"""Disposable Data Platform acceptance on real PostgreSQL/pgvector.

Never connects to, migrates or writes the production arvectum_data database.
The only optional production dependencies are read-only localhost model inference.
Run from the repository root with the project's Python environment.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
CONTAINER = "arvectum-postgres"


def _psql(sql: str, *, database: str | None = None) -> None:
    shell = (
        'exec psql -U "$POSTGRES_USER" -d "$1" -v ON_ERROR_STOP=1 -c "$2"'
        if database else
        'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "$1"'
    )
    args = ["docker", "exec", CONTAINER, "sh", "-c", shell, "sh"]
    if database:
        args.append(database)
    args.append(sql)
    subprocess.run(args, check=True, capture_output=True, text=True, timeout=30)


@contextmanager
def isolated_database():
    suffix = uuid.uuid4().hex[:12]
    name, role = f"dp_e2e_{suffix}", f"dp_e2e_user_{suffix}"
    secret = secrets.token_hex(24)
    role_created = database_created = False
    try:
        _psql(f"CREATE ROLE {role} LOGIN PASSWORD '{secret}'")
        role_created = True
        _psql(f"CREATE DATABASE {name} OWNER {role}")
        database_created = True
        # pgvector is installed as a PostgreSQL superuser in the disposable DB.
        _psql("CREATE EXTENSION IF NOT EXISTS vector", database=name)
        yield f"postgresql+psycopg://{role}:{secret}@127.0.0.1:55432/{name}"
    finally:
        if database_created:
            _psql(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        if role_created:
            _psql(f"DROP ROLE IF EXISTS {role}")


@contextmanager
def isolated_environment(db_url: str):
    old = {k: v for k, v in os.environ.items() if k.startswith("ARVECTUM_DATA_")}
    for key in old:
        os.environ.pop(key)
    os.environ["ARVECTUM_DATA_DATABASE_URL"] = db_url
    try:
        yield
    finally:
        for key in list(os.environ):
            if key.startswith("ARVECTUM_DATA_"):
                os.environ.pop(key)
        os.environ.update(old)


def _post(client: TestClient, path: str, payload: dict, *, expected: int = 200):
    response = client.post(path, headers=client._dp_headers, json=payload)
    assert response.status_code == expected, (path, response.status_code, response.text[:500])
    return response.json()


def run(*, live_embeddings: bool, with_answer: bool) -> dict:
    from arvectum_data.api.app import create_app
    from arvectum_data.api.config import Settings

    if with_answer and not live_embeddings:
        raise ValueError("--with-answer requires --live-embeddings")
    report: dict[str, object] = {
        "database": "disposable (auto-deleted)",
        "embeddings": "Qwen3-Embedding-4B" if live_embeddings else "hashing",
        "checks": [],
    }
    with isolated_database() as db_url, isolated_environment(db_url):
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        api_secret, consumer_secret = secrets.token_urlsafe(24), secrets.token_urlsafe(24)

        def new_client() -> TestClient:
            settings = Settings(
                _env_file=None,
                deployment_mode="local-private",
                environment="isolated-e2e",
                database_url=db_url,
                internal_api_key=api_secret,
                consumer_api_keys={"e2e-reader": consumer_secret},
                embedding_provider="llama_cpp" if live_embeddings else "hashing",
                embedding_model="Qwen3-Embedding-4B" if live_embeddings else "dp-e2e-hash",
                embedding_dimension=2560 if live_embeddings else 64,
                embedding_base_url="http://127.0.0.1:8090/v1",
                reasoning_policy="local-only" if with_answer else "disabled",
                reasoning_provider="openai-compatible",
                reasoning_model="arvectum-gemma4-12b-it-qat-q4_0" if with_answer else "",
                reasoning_base_url="http://127.0.0.1:8081/v1",
                reasoning_locality="local",
                model_timeout_seconds=100,
                cross_encoder_provider="disabled",
                vision_policy="disabled",
                ocr_provider="disabled",
            )
            assert settings.database_url == db_url
            app = create_app(settings)
            client = TestClient(app)
            client._dp_headers = {"X-Arvectum-Key": api_secret}
            return client

        collection, protected = "e2e:public", "e2e:restricted"
        with new_client() as client:
            for cid, access in ((collection, None), (protected, {"allowed_consumers": ["e2e-reader"]})):
                payload = {"collection_id": cid, "owner": "e2e", "name": cid, "default_language": "russian"}
                if access:
                    payload["access_policy"] = access
                _post(client, "/v1/collections", payload)
            report["checks"].append("collection_creation")

            def ingest(cid: str, uri: str, content: str):
                response = client.post(
                    "/v1/ingest/document",
                    headers=client._dp_headers,
                    data={"collection_id": cid, "canonical_uri": uri, "pre_chunked": "true"},
                    files={"file": ("fixture.txt", content.encode("utf-8"), "text/plain")},
                )
                assert response.status_code == 200, (response.status_code, response.text[:500])
                assert response.json()["embeddings"] > 0
                return response.json()

            text = (
                "Синтетический учебный документ: насос МЕТЕОР-42 имеет "
                "производительность 75 литров в минуту. Срок обслуживания 18 месяцев. "
            ) * 12
            first = ingest(collection, "e2e://meteor", text)
            repeated = ingest(collection, "e2e://meteor", text)
            assert repeated["document_id"] == first["document_id"]
            assert repeated["embeddings_written"] == 0
            report["checks"].append("idempotent_ingest_with_embeddings")
            ingest(protected, "e2e://restricted", "Защищённая инструкция для модели МЕТЕОР-42. " * 15)

            revision = _post(client, "/v1/index/rebuild", {"collection_id": collection})
            assert revision["status"] == "completed"
            active_revision = revision["revision"]
            report["checks"].append("durable_index_revision")

            query = {"query": "Производительность насоса МЕТЕОР-42", "collections": [collection], "mode": "hybrid"}
            hits = _post(client, "/v1/search", query)["hits"]
            assert hits
            assert hits[0]["scores"]["lexical"] is not None
            assert hits[0]["scores"]["vector"] is not None
            assert hits[0]["evidence"][0]["canonical_uri"] == "e2e://meteor"
            report["checks"].append("hybrid_provenance")

            _post(client, "/v1/search", {"query": "инструкция", "collections": [protected]}, expected=403)
            _post(client, "/v1/search", {"query": "инструкция", "collections": [collection, protected]}, expected=403)
            reader_headers = {**client._dp_headers, "X-Arvectum-Consumer": "e2e-reader",
                              "X-Arvectum-Consumer-Key": consumer_secret}
            allowed = client.post("/v1/search", headers=reader_headers,
                                  json={"query": "инструкция", "collections": [protected]})
            assert allowed.status_code == 200 and allowed.json()["hits"]
            report["checks"].append("fail_closed_acl")

            if with_answer:
                answer = _post(client, "/v1/answer",
                               {"query": query["query"], "collections": [collection], "evidence_limit": 3})
                assert answer["evidence"] and (answer["answer"] or answer["abstained"])
                report["checks"].append("localhost_grounded_answer")

            ingest(collection, "e2e://second", "Дополнительный регламент эксплуатации. " * 35)
            provider = client.app.state.platform_service.embedding_provider

            class BrokenProvider:
                provider_name = provider.provider_name
                model_name = provider.model_name
                dimension = provider.dimension

                def embed_texts(self, texts):
                    raise RuntimeError("intentional isolated rebuild failure")

                def embed_query(self, text):
                    raise RuntimeError("intentional isolated rebuild failure")

            client.app.state.platform_service.embedding_provider = BrokenProvider()
            failed = client.post("/v1/index/rebuild", headers=client._dp_headers,
                                 json={"collection_id": collection})
            assert failed.status_code == 500, (failed.status_code, failed.text[:300])
            stats = client.get(f"/v1/collections/{collection}/stats", headers=client._dp_headers)
            assert stats.status_code == 200 and stats.json()["active_index_revision"] == active_revision
            report["checks"].append("failed_rebuild_preserves_active_revision")

        # Re-instantiating the service verifies persistence independent of app memory.
        with new_client() as restarted:
            stats = restarted.get(f"/v1/collections/{collection}/stats", headers=restarted._dp_headers)
            assert stats.status_code == 200 and stats.json()["active_index_revision"] == active_revision
            assert _post(restarted, "/v1/search", query)["hits"]
            report["checks"].append("service_reinitialization_recovery")
            recovered = _post(restarted, "/v1/index/rebuild", {"collection_id": collection})
            assert recovered["status"] == "completed"
            assert recovered["revision"] != active_revision
            report["checks"].append("revision_recovery_after_failure")
    report["result"] = "PASS"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-embeddings", action="store_true")
    parser.add_argument("--with-answer", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(run(live_embeddings=args.live_embeddings,
                             with_answer=args.with_answer), ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
