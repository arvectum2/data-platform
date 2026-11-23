"""Bounded synthetic-only ingest experiment against ONE disposable PostgreSQL container.

Refuses arbitrary connection strings. Its only database target is the published
loopback port and disposable database created by the matching staging runbook.
No production API, original sources, source URLs, model servers, or collections.
"""
from __future__ import annotations

import argparse
import contextvars
import hashlib
import importlib
import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text

from arvectum_data.api.config import Settings
from arvectum_data.api.service import DataPlatformService
from arvectum_data.documents import ingest_bytes
from arvectum_data.indexing.embeddings import HashingEmbeddingProvider
from arvectum_data.storage.postgres import Base, build_engine

DATABASE_URL = "postgresql+psycopg://staging:staging@127.0.0.1:55435/dp_ingest_slo_staging"
COLLECTION_ID = "synthetic:ingest-slo"
SUPPORTED_SIZES = (8192, 65536)
SUPPORTED_CONCURRENCY = (1, 4)
SAMPLES_PER_COHORT = 20
MAX_SAMPLES = 160
PHASE_CTX: contextvars.ContextVar[dict[str, int] | None] = contextvars.ContextVar(
    "staging_phases", default=None
)


class TimedHashingProvider(HashingEmbeddingProvider):
    """Deliberately lightweight baseline: not the real production embedding model."""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        state = PHASE_CTX.get()
        started = time.perf_counter_ns()
        try:
            return super().embed_texts(texts)
        finally:
            if state is not None:
                state["embed_ns"] += time.perf_counter_ns() - started
                state["embedding_calls"] += 1


def synthetic_payload(size: int, number: int) -> bytes:
    if size not in SUPPORTED_SIZES or number < 0:
        raise ValueError("unapproved synthetic input size/number")
    seed = f"synthetic staging token alpha beta gamma {number:05d} ".encode("ascii")
    return (seed * ((size // len(seed)) + 1))[:size]


def _ceil_ms(ns: int) -> int:
    return math.ceil(ns / 1_000_000)


def _floor_ms(ns: int) -> int:
    return max(0, ns // 1_000_000)


def _measure_one(
    service: DataPlatformService,
    *,
    size: int,
    concurrency: int,
    number: int,
) -> dict[str, int | bool]:
    content = synthetic_payload(size, number)
    state = {"decode_ns": 0, "embed_ns": 0, "embedding_calls": 0}
    token = PHASE_CTX.set(state)
    started = time.perf_counter_ns()
    try:
        stage_start = time.perf_counter_ns()
        ingest = ingest_bytes(
            content,
            filename="synthetic-staging.txt",
            collection_id=COLLECTION_ID,
            canonical_uri=f"synthetic://isolated-stage/{size}/{concurrency}/{number}",
            title="synthetic-staging",
        )
        extracted_ns = time.perf_counter_ns() - stage_start
        persist_start = time.perf_counter_ns()
        result = service._persist_and_index(ingest)
        persist_ns = time.perf_counter_ns() - persist_start
        whole_ns = time.perf_counter_ns() - started
        # Time in _persist_and_index except the provider itself is non-inference
        # persistence/ORM/validation cost. Not a pure SQL span.
        non_embed_persist_ns = max(0, persist_ns - state["embed_ns"])
        if state["embedding_calls"] != result["embedding_attempts"]:
            raise RuntimeError("unexpected retry or provider call count in synthetic hashing experiment")
        record: dict[str, int | bool] = {
            "synthetic": True,
            "bytes": len(content),
            "chunks": len(ingest.chunks),
            "concurrency": concurrency,
            "retry_count": 0,
            "status_code": 200,
            "total_ms": _ceil_ms(whole_ns),
            "decode_ms": _floor_ms(state["decode_ns"]),
            "chunk_ms": _floor_ms(max(0, extracted_ns - state["decode_ns"])),
            "embed_ms": _floor_ms(state["embed_ns"]),
            "db_ms": _floor_ms(non_embed_persist_ns),
        }
        return record
    finally:
        PHASE_CTX.reset(token)


def _prepare_clean_disposable_storage() -> None:
    # Hardcoded synthetic-only DSN, so ambient env vars cannot route a query
    # to the real TA+DP shared physical cluster or the separate TA-PITR cluster.
    if os.environ.get("ARVECTUM_DATA_DATABASE_URL"):
        raise ValueError("ambient production database env must be absent")
    engine = build_engine(DATABASE_URL)
    try:
        with engine.begin() as conn:
            current_db = conn.execute(text("SELECT current_database()")).scalar_one()
            if current_db != "dp_ingest_slo_staging":
                raise RuntimeError("unexpected disposable target database identity")
        if inspect(engine).has_table("dp_collections"):
            raise RuntimeError("disposable staging target is not pristine")
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()


def run_bounded_experiment(output: Path) -> dict[str, object]:
    if output.suffix != ".jsonl" or output.exists() or output.is_symlink():
        raise ValueError("output must be a new private JSONL file")
    if output.parent.resolve() != Path("/tmp").resolve():
        raise ValueError("output path must be directly inside /tmp")
    _prepare_clean_disposable_storage()
    settings = Settings(
        _env_file=None,
        environment="synthetic-staging",
        database_url=DATABASE_URL,
        deployment_mode="local-private",
        embedding_provider="hashing",
        embedding_model="local-hash-v1",
        embedding_dimension=64,
        cross_encoder_provider="disabled",
        reasoning_policy="disabled",
        vision_policy="disabled",
        embedding_retry_max_attempts=1,
        max_chunks_per_ingest=1000,
    )
    service = DataPlatformService(settings, embedding_provider=TimedHashingProvider(dimension=64))
    service.create_collection(
        collection_id=COLLECTION_ID,
        owner="synthetic-only",
        name="Disposable synthetic staging",
        default_language="russian",
    )

    ingest_module = importlib.import_module("arvectum_data.documents.ingest")
    original_extract = ingest_module.extract_text

    def measured_extract(*args: Any, **kwargs: Any) -> Any:
        state = PHASE_CTX.get()
        started = time.perf_counter_ns()
        try:
            return original_extract(*args, **kwargs)
        finally:
            if state is not None:
                state["decode_ns"] += time.perf_counter_ns() - started

    records: list[dict[str, int | bool]] = []
    ingest_module.extract_text = measured_extract
    try:
        for size in SUPPORTED_SIZES:
            for concurrency in SUPPORTED_CONCURRENCY:
                # Fixed sample count per cell; no retries, dynamic enlargement
                # or unbounded executor. Hashing does NOT call network models.
                with ThreadPoolExecutor(max_workers=concurrency) as pool:
                    jobs = [
                        pool.submit(
                            _measure_one,
                            service,
                            size=size,
                            concurrency=concurrency,
                            number=number,
                        )
                        for number in range(SAMPLES_PER_COHORT)
                    ]
                    for job in jobs:
                        records.append(job.result())
    finally:
        ingest_module.extract_text = original_extract

    if len(records) != len(SUPPORTED_SIZES) * len(SUPPORTED_CONCURRENCY) * SAMPLES_PER_COHORT:
        raise RuntimeError("synthetic stage did not finish all planned observations")
    if len(records) > MAX_SAMPLES:
        raise RuntimeError("synthetic experiment exceeded request budget")
    # Atomic create/exclusive + mode0600, no source payloads in the stored trace.
    descriptor = os.open(str(output), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    return {
        "status": "synthetic_only_completed",
        "rows": len(records),
        "provider": "hashing:local-hash-v1:64",
        "production_used": False,
        "source_documents_used": False,
        "production_slo_proven": False,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_bounded_experiment(args.output)
    except (ValueError, OSError, RuntimeError) as exc:
        parser.error(f"disposable synthetic benchmark failed: {type(exc).__name__}")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
