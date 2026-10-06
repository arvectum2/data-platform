from __future__ import annotations

import argparse
import json
import math
import os
import time
import urllib.request
import uuid
from pathlib import Path
from urllib.error import HTTPError

import psycopg

from arvectum_data.evaluation.models import EvaluationSuite
from arvectum_data.evaluation.core import evaluate_case


def _http_json(
    base_url: str,
    method: str,
    path: str,
    payload: dict | None = None,
    *,
    timeout: float = 60.0,
) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        if exc.code == 404 and method == "DELETE":
            return {}
        raise
    return json.loads(raw) if raw else {}


def _database_url() -> str:
    value = os.getenv("ARVECTUM_DATA_DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("ARVECTUM_DATA_DATABASE_URL is not configured")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _load_collection_vectors(collection_id: str):
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT embedding_provider, embedding_model, embedding_dimension
                FROM dp_collections
                WHERE collection_id = %s
                """,
                (collection_id,),
            )
            collection = cursor.fetchone()
            if collection is None:
                raise RuntimeError(f"collection not found: {collection_id}")
            provider, model, dimension = collection
            cursor.execute(
                """
                SELECT c.chunk_id, r.canonical_uri, e.vector::text
                FROM dp_resources AS r
                JOIN dp_documents AS d ON d.resource_id = r.resource_id
                JOIN dp_chunks AS c ON c.document_id = d.document_id
                JOIN dp_chunk_embeddings AS e ON e.chunk_id = c.chunk_id
                WHERE r.collection_id = %s
                  AND e.provider = %s
                  AND e.model = %s
                ORDER BY c.chunk_id
                """,
                (collection_id, provider, model),
            )
            rows = cursor.fetchall()
    return str(provider), str(model), int(dimension), rows


def _embed_query(base_url: str, model: str, query: str) -> list[float]:
    payload = {"model": model, "input": [query]}
    data = _http_json(
        base_url,
        "POST",
        "/embeddings",
        payload,
        timeout=60,
    )
    return [float(value) for value in data["data"][0]["embedding"]]


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = int(math.floor(position))
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare Qdrant vector retrieval against a frozen Data Platform suite."
    )
    parser.add_argument("suite", type=Path)
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--qdrant-collection", default="arvectum_reference")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    suite = EvaluationSuite.from_dict(
        json.loads(args.suite.read_text(encoding="utf-8"))
    )
    if not suite.cases:
        raise RuntimeError("benchmark suite is empty")

    collections = {
        collection_id
        for case in suite.cases
        for collection_id in case.collections
    }
    if len(collections) != 1:
        raise RuntimeError(
            "Qdrant reference runner currently requires exactly one collection"
        )
    collection_id = next(iter(collections))
    provider, model, dimension, rows = _load_collection_vectors(collection_id)

    _http_json(
        args.qdrant_url,
        "DELETE",
        f"/collections/{args.qdrant_collection}",
    )
    _http_json(
        args.qdrant_url,
        "PUT",
        f"/collections/{args.qdrant_collection}",
        {"vectors": {"size": dimension, "distance": "Cosine"}},
    )

    points: list[dict] = []
    for chunk_id, canonical_uri, vector_text in rows:
        vector = [
            float(value)
            for value in str(vector_text).strip("[]").split(",")
        ]
        points.append(
            {
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, str(chunk_id))),
                "vector": vector,
                "payload": {
                    "chunk_id": str(chunk_id),
                    "canonical_uri": str(canonical_uri),
                },
            }
        )
        if len(points) >= args.batch_size:
            _http_json(
                args.qdrant_url,
                "PUT",
                f"/collections/{args.qdrant_collection}/points?wait=true",
                {"points": points},
                timeout=120,
            )
            points = []
    if points:
        _http_json(
            args.qdrant_url,
            "PUT",
            f"/collections/{args.qdrant_collection}/points?wait=true",
            {"points": points},
            timeout=120,
        )

    embedding_base_url = os.getenv(
        "ARVECTUM_DATA_EMBEDDING_BASE_URL",
        "http://127.0.0.1:8090/v1",
    ).rstrip("/")

    results = []
    search_latencies: list[float] = []
    end_to_end_latencies: list[float] = []
    for case in suite.cases:
        total_started = time.perf_counter()
        vector = _embed_query(embedding_base_url, model, case.query)
        started = time.perf_counter()
        response = _http_json(
            args.qdrant_url,
            "POST",
            f"/collections/{args.qdrant_collection}/points/query",
            {"query": vector, "limit": case.limit, "with_payload": True},
            timeout=30,
        )
        latency_ms = (time.perf_counter() - started) * 1000.0
        end_to_end_ms = (time.perf_counter() - total_started) * 1000.0
        search_latencies.append(latency_ms)
        end_to_end_latencies.append(end_to_end_ms)
        hits = [
            {
                "canonical_uri": str(point["payload"]["canonical_uri"]),
                "chunk_id": str(point["payload"]["chunk_id"]),
            }
            for point in response["result"]["points"]
        ]
        results.append(
            evaluate_case(case, hits=hits, latency_ms=latency_ms)
        )

    reference_info = _http_json(args.qdrant_url, "GET", "/")
    summary = {
        "reference": "Qdrant",
        "reference_version": str(reference_info.get("version") or ""),
        "reference_commit": str(reference_info.get("commit") or ""),
        "suite_name": suite.name,
        "collection_id": collection_id,
        "collection_points": len(rows),
        "embedding_provider": provider,
        "embedding_model": model,
        "dimension": dimension,
        "cases": len(results),
        "top1_accuracy": sum(1 for item in results if item.top1) / len(results),
        "mrr": sum(item.reciprocal_rank for item in results) / len(results),
        "mean_recall_at_5": sum(item.recall_at_5 for item in results) / len(results),
        "mean_ndcg_at_5": sum(item.ndcg_at_5 for item in results) / len(results),
        "search_latency_p50_ms": _percentile(search_latencies, 0.50),
        "search_latency_p95_ms": _percentile(search_latencies, 0.95),
        "search_latency_max_ms": max(search_latencies, default=0.0),
        "end_to_end_latency_p50_ms": _percentile(end_to_end_latencies, 0.50),
        "end_to_end_latency_p95_ms": _percentile(end_to_end_latencies, 0.95),
        "end_to_end_latency_max_ms": max(end_to_end_latencies, default=0.0),
    }
    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
