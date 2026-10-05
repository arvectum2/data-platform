# Vector index benchmark and production decision

Date: 2026-10-05

## Decision

Keep full-precision exact pgvector cosine search as the production strategy for the
current corpus.

HNSW and IVFFlat are both substantially faster in isolation, but on the current
real workload the absolute exact-search latency is already only a few milliseconds
while the tested ANN variants reduce recall@10. That is not a worthwhile
quality/complexity trade for retrieval yet.

ANN remains a measured optimization gate rather than a default. Re-run this
benchmark when exact vector search becomes a material part of end-to-end search
latency or the corpus grows substantially. An ANN strategy may be enabled only
when it demonstrates acceptable retrieval quality against the exact baseline on
the then-current production corpus.

## Workload

The benchmark used the live Data Platform embedding identity, copied into a
temporary PostgreSQL table in one database session. It did not create persistent
tables or indexes and did not modify production rows.

- PostgreSQL extension: pgvector 0.8.7
- provider: `llama_cpp`
- model: `Qwen3-Embedding-4B`
- dimension: 2560
- vectors: 697
- deterministic sampled queries: 100
- `k`: 10
- repetitions per query: 5
- distance: cosine

The full result is stored in
`docs/benchmarks/vector-index-2026-10-05.json`.

Because the active model has 2560 dimensions, ANN candidates are benchmarked as
`halfvec(2560)` expression indexes while canonical embeddings remain stored at
full precision. The exact production baseline remains the full `vector` value.

## Results

| Strategy | p50 | p95 | mean | recall@10 | min recall@10 | build | index |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| exact `vector` float32 | 2.940 ms | 3.321 ms | 2.981 ms | 100.0% | 100.0% | n/a | n/a |
| exact `halfvec` float16 | 4.360 ms | 4.664 ms | 4.396 ms | 100.0% | 100.0% | n/a | n/a |
| HNSW m=16, ef=40 | 0.433 ms | 0.499 ms | 0.444 ms | 93.9% | 70.0% | 89.1 ms | 3.40 MB |
| HNSW m=16, ef=100 | 0.492 ms | 0.564 ms | 0.496 ms | 93.9% | 70.0% | 89.1 ms | 3.40 MB |
| HNSW m=32, efc=128, ef=100 | 0.547 ms | 0.647 ms | 0.550 ms | 93.9% | 70.0% | 185.2 ms | 3.40 MB |
| IVFFlat lists=1, probes=1 | 0.580 ms | 0.686 ms | 0.594 ms | 95.2% | 80.0% | 14.6 ms | 5.73 MB |
| IVFFlat lists=26, probes=5 | 0.431 ms | 0.518 ms | 0.436 ms | 95.5% | 80.0% | 29.2 ms | 5.93 MB |
| IVFFlat lists=26, probes=13 | 0.533 ms | 0.624 ms | 0.541 ms | 95.2% | 70.0% | 29.0 ms | 5.93 MB |

The benchmark also isolates the half-precision cast: exact `halfvec` preserved
the sampled top-10 perfectly, so the observed recall loss comes from the tested
ANN retrieval paths rather than merely converting the vectors to half precision.

## Production gate

For now:

1. store canonical embeddings at full precision;
2. use exact collection-scoped cosine search;
3. do not create persistent HNSW or IVFFlat indexes;
4. retain the benchmark harness for repeatable future decisions;
5. compare any future ANN candidate with full exact search and require retrieval
   quality to remain within the product's accepted relevance envelope before
   enabling it.

Run the benchmark with:

```bash
ARVECTUM_DATA_DATABASE_URL=... \
python scripts/benchmark_vector_indexes.py \
  --queries 100 \
  --k 10 \
  --repeats 5
```

The script uses only temporary benchmark objects.
