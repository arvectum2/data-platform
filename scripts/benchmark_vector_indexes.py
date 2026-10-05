#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import create_engine, text


@dataclass(frozen=True)
class BenchmarkResult:
    strategy: str
    rows: int
    dimension: int
    queries: int
    k: int
    build_ms: float | None
    index_bytes: int | None
    p50_ms: float
    p95_ms: float
    mean_ms: float
    recall_at_k: float
    min_recall_at_k: float
    settings: dict[str, Any]


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _run_queries(
    conn,
    *,
    sql: str,
    query_ids: list[str],
    exact: dict[str, list[str]],
    k: int,
    repeats: int,
) -> tuple[list[float], list[float], dict[str, list[str]]]:
    timings: list[float] = []
    recalls: list[float] = []
    observed: dict[str, list[str]] = {}
    for query_id in query_ids:
        best_elapsed = float("inf")
        result_ids: list[str] = []
        for _ in range(repeats):
            started = time.perf_counter()
            rows = conn.execute(text(sql), {"query_id": query_id, "limit": k}).all()
            elapsed = (time.perf_counter() - started) * 1000
            if elapsed < best_elapsed:
                best_elapsed = elapsed
                result_ids = [str(row.embedding_id) for row in rows]
        timings.append(best_elapsed)
        observed[query_id] = result_ids
        baseline = exact.get(query_id, [])
        if baseline:
            recalls.append(len(set(result_ids) & set(baseline)) / len(baseline))
        else:
            recalls.append(1.0)
    return timings, recalls, observed


def _result(
    *,
    strategy: str,
    rows: int,
    dimension: int,
    queries: int,
    k: int,
    build_ms: float | None,
    index_bytes: int | None,
    timings: list[float],
    recalls: list[float],
    settings: dict[str, Any],
) -> BenchmarkResult:
    return BenchmarkResult(
        strategy=strategy,
        rows=rows,
        dimension=dimension,
        queries=queries,
        k=k,
        build_ms=None if build_ms is None else round(build_ms, 3),
        index_bytes=index_bytes,
        p50_ms=round(_percentile(timings, 0.50), 3),
        p95_ms=round(_percentile(timings, 0.95), 3),
        mean_ms=round(statistics.fmean(timings), 3),
        recall_at_k=round(statistics.fmean(recalls), 4),
        min_recall_at_k=round(min(recalls) if recalls else 1.0, 4),
        settings=settings,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark exact pgvector search against temporary HNSW/IVFFlat halfvec indexes. "
            "All benchmark tables/indexes are TEMP objects scoped to one database session."
        )
    )
    parser.add_argument("--database-url", default=os.getenv("ARVECTUM_DATA_DATABASE_URL", ""))
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--dimension", type=int)
    parser.add_argument("--queries", type=int, default=40)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--json-output")
    args = parser.parse_args()

    if not args.database_url:
        parser.error("--database-url or ARVECTUM_DATA_DATABASE_URL is required")
    if args.queries < 1 or args.k < 1 or args.repeats < 1:
        parser.error("--queries, --k and --repeats must be positive")

    engine = create_engine(args.database_url)
    results: list[BenchmarkResult] = []

    with engine.connect() as conn:
        identity_conditions: list[str] = []
        identity_params: dict[str, Any] = {}
        if args.provider is not None:
            identity_conditions.append("provider = :provider")
            identity_params["provider"] = args.provider
        if args.model is not None:
            identity_conditions.append("model = :model")
            identity_params["model"] = args.model
        if args.dimension is not None:
            identity_conditions.append("dimension = :dimension")
            identity_params["dimension"] = args.dimension
        identity_where = (
            "WHERE " + " AND ".join(identity_conditions)
            if identity_conditions
            else ""
        )
        identity = conn.execute(
            text(
                f"""
                SELECT provider, model, dimension, count(*) AS rows
                FROM dp_chunk_embeddings
                {identity_where}
                GROUP BY provider, model, dimension
                ORDER BY count(*) DESC, provider, model, dimension
                LIMIT 1
                """
            ),
            identity_params,
        ).mappings().first()
        if identity is None:
            raise SystemExit("No matching embeddings found")

        provider = str(identity["provider"])
        model = str(identity["model"])
        dimension = int(identity["dimension"])

        if dimension > 4000:
            raise SystemExit(
                f"dimension {dimension} exceeds pgvector halfvec ANN index limit (4000)"
            )

        conn.execute(
            text(
                """
                CREATE TEMP TABLE dp_vec_bench
                ON COMMIT DROP
                AS
                SELECT embedding_id, vector
                FROM dp_chunk_embeddings
                WHERE provider = :provider
                  AND model = :model
                  AND dimension = :dimension
                """
            ),
            {"provider": provider, "model": model, "dimension": dimension},
        )
        conn.execute(text("ALTER TABLE dp_vec_bench ADD PRIMARY KEY (embedding_id)"))
        conn.execute(text("ANALYZE dp_vec_bench"))

        row_count = int(conn.execute(text("SELECT count(*) FROM dp_vec_bench")).scalar_one())
        if row_count <= args.k:
            raise SystemExit(f"Need more than k={args.k} rows; found {row_count}")

        query_count = min(args.queries, row_count)
        query_ids = [
            str(row.embedding_id)
            for row in conn.execute(
                text(
                    """
                    SELECT embedding_id
                    FROM dp_vec_bench
                    ORDER BY md5(embedding_id)
                    LIMIT :limit
                    """
                ),
                {"limit": query_count},
            )
        ]

        full_exact_sql = """
            SELECT embedding_id
            FROM dp_vec_bench
            ORDER BY vector <=> (
                SELECT vector FROM dp_vec_bench WHERE embedding_id = :query_id
            )
            LIMIT :limit
        """
        conn.execute(text("SET LOCAL enable_indexscan = off"))
        conn.execute(text("SET LOCAL enable_bitmapscan = off"))
        conn.execute(text("SET LOCAL enable_seqscan = on"))
        exact_timings, _, exact = _run_queries(
            conn,
            sql=full_exact_sql,
            query_ids=query_ids,
            exact={},
            k=args.k,
            repeats=args.repeats,
        )
        results.append(
            _result(
                strategy="exact-vector",
                rows=row_count,
                dimension=dimension,
                queries=query_count,
                k=args.k,
                build_ms=None,
                index_bytes=None,
                timings=exact_timings,
                recalls=[1.0] * query_count,
                settings={"precision": "float32", "planner": "sequential-scan"},
            )
        )

        half_expr = f"(vector::halfvec({dimension}))"
        half_query = (
            f"{half_expr} <=> "
            f"((SELECT vector FROM dp_vec_bench WHERE embedding_id = :query_id)::halfvec({dimension}))"
        )
        exact_half_sql = f"""
            SELECT embedding_id
            FROM dp_vec_bench
            ORDER BY {half_query}
            LIMIT :limit
        """
        half_timings, half_recalls, _ = _run_queries(
            conn,
            sql=exact_half_sql,
            query_ids=query_ids,
            exact=exact,
            k=args.k,
            repeats=args.repeats,
        )
        results.append(
            _result(
                strategy="exact-halfvec",
                rows=row_count,
                dimension=dimension,
                queries=query_count,
                k=args.k,
                build_ms=None,
                index_bytes=None,
                timings=half_timings,
                recalls=half_recalls,
                settings={"precision": "float16", "planner": "sequential-scan"},
            )
        )

        half_query = (
            f"{half_expr} <=> "
            f"((SELECT vector FROM dp_vec_bench WHERE embedding_id = :query_id)::halfvec({dimension}))"
        )
        ann_sql = f"""
            SELECT embedding_id
            FROM dp_vec_bench
            ORDER BY {half_query}
            LIMIT :limit
        """

        conn.execute(text("SET LOCAL enable_indexscan = on"))
        conn.execute(text("SET LOCAL enable_bitmapscan = on"))
        conn.execute(text("SET LOCAL enable_seqscan = off"))

        hnsw_name = "dp_vec_bench_hnsw"
        started = time.perf_counter()
        conn.execute(
            text(
                f"""
                CREATE INDEX {hnsw_name}
                ON dp_vec_bench
                USING hnsw ({half_expr} halfvec_cosine_ops)
                WITH (m = 16, ef_construction = 64)
                """
            )
        )
        hnsw_build_ms = (time.perf_counter() - started) * 1000
        hnsw_bytes = int(
            conn.execute(text(f"SELECT pg_relation_size('{hnsw_name}')")).scalar_one()
        )
        conn.execute(text("ANALYZE dp_vec_bench"))
        for ef_search in (40, 100):
            conn.execute(text(f"SET LOCAL hnsw.ef_search = {ef_search}"))
            hnsw_timings, hnsw_recalls, _ = _run_queries(
                conn,
                sql=ann_sql,
                query_ids=query_ids,
                exact=exact,
                k=args.k,
                repeats=args.repeats,
            )
            results.append(
                _result(
                    strategy=f"hnsw-halfvec-ef{ef_search}",
                    rows=row_count,
                    dimension=dimension,
                    queries=query_count,
                    k=args.k,
                    build_ms=hnsw_build_ms,
                    index_bytes=hnsw_bytes,
                    timings=hnsw_timings,
                    recalls=hnsw_recalls,
                    settings={
                        "m": 16,
                        "ef_construction": 64,
                        "ef_search": ef_search,
                    },
                )
            )
        conn.execute(text(f"DROP INDEX {hnsw_name}"))

        hnsw_hq_name = "dp_vec_bench_hnsw_hq"
        started = time.perf_counter()
        conn.execute(
            text(
                f"""
                CREATE INDEX {hnsw_hq_name}
                ON dp_vec_bench
                USING hnsw ({half_expr} halfvec_cosine_ops)
                WITH (m = 32, ef_construction = 128)
                """
            )
        )
        hnsw_hq_build_ms = (time.perf_counter() - started) * 1000
        hnsw_hq_bytes = int(
            conn.execute(text(f"SELECT pg_relation_size('{hnsw_hq_name}')")).scalar_one()
        )
        conn.execute(text("ANALYZE dp_vec_bench"))
        conn.execute(text("SET LOCAL hnsw.ef_search = 100"))
        hnsw_hq_timings, hnsw_hq_recalls, _ = _run_queries(
            conn,
            sql=ann_sql,
            query_ids=query_ids,
            exact=exact,
            k=args.k,
            repeats=args.repeats,
        )
        results.append(
            _result(
                strategy="hnsw-halfvec-high-recall",
                rows=row_count,
                dimension=dimension,
                queries=query_count,
                k=args.k,
                build_ms=hnsw_hq_build_ms,
                index_bytes=hnsw_hq_bytes,
                timings=hnsw_hq_timings,
                recalls=hnsw_hq_recalls,
                settings={"m": 32, "ef_construction": 128, "ef_search": 100},
            )
        )
        conn.execute(text(f"DROP INDEX {hnsw_hq_name}"))

        # Evaluate both the pgvector small-corpus heuristic and an intentionally
        # more partitioned IVFFlat configuration to expose its recall sensitivity.
        partitioned_lists = max(4, round(math.sqrt(row_count)))
        ivf_configs = [
            ("ivfflat-halfvec-recommended", max(1, row_count // 1000), 1),
            (
                "ivfflat-halfvec-partitioned",
                partitioned_lists,
                max(1, round(math.sqrt(partitioned_lists))),
            ),
            (
                "ivfflat-halfvec-high-recall",
                partitioned_lists,
                max(1, math.ceil(partitioned_lists / 2)),
            ),
        ]
        seen: set[tuple[int, int]] = set()
        for label, lists, probes in ivf_configs:
            key = (lists, min(probes, lists))
            if key in seen:
                continue
            seen.add(key)
            probes = min(probes, lists)
            index_name = "dp_vec_bench_ivfflat"
            started = time.perf_counter()
            conn.execute(
                text(
                    f"""
                    CREATE INDEX {index_name}
                    ON dp_vec_bench
                    USING ivfflat ({half_expr} halfvec_cosine_ops)
                    WITH (lists = {lists})
                    """
                )
            )
            build_ms = (time.perf_counter() - started) * 1000
            index_bytes = int(
                conn.execute(text(f"SELECT pg_relation_size('{index_name}')")).scalar_one()
            )
            conn.execute(text("ANALYZE dp_vec_bench"))
            conn.execute(text(f"SET LOCAL ivfflat.probes = {probes}"))
            timings, recalls, _ = _run_queries(
                conn,
                sql=ann_sql,
                query_ids=query_ids,
                exact=exact,
                k=args.k,
                repeats=args.repeats,
            )
            results.append(
                _result(
                    strategy=label,
                    rows=row_count,
                    dimension=dimension,
                    queries=query_count,
                    k=args.k,
                    build_ms=build_ms,
                    index_bytes=index_bytes,
                    timings=timings,
                    recalls=recalls,
                    settings={"lists": lists, "probes": probes},
                )
            )
            conn.execute(text(f"DROP INDEX {index_name}"))

        payload = {
            "identity": {
                "provider": provider,
                "model": model,
                "dimension": dimension,
                "rows": row_count,
            },
            "results": [asdict(result) for result in results],
        }
        rendered = json.dumps(payload, indent=2, ensure_ascii=False)
        print(rendered)
        if args.json_output:
            with open(args.json_output, "w", encoding="utf-8") as handle:
                handle.write(rendered + "\n")

        conn.rollback()

    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
