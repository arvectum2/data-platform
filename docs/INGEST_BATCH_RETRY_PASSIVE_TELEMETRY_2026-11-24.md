# Ingest embedding batches vs actual retries — source-only evidence

Scope: Data Platform #133, passive numeric metrics only; NOT an optimization
of model inference, indexing semantics, source integrity or batching settings.

## Independent running-system evidence (24 November 2026, 19:03 MSK)

Authenticated read-only GET support/readiness, latest 256 ingest requests:

- Request p95 34,275 ms; embedding phase p95 34,085 ms.
- Other phases: prepare p95 63 ms, lookup 12 ms, persist 231 ms.
- Input: all 256 up_to_64kib; concurrency: all 256 single request.
- Chunk cohorts: 1-3 (92 samples, p95 5,734 ms); 4-8 (67, 8,386);
  9-16 (34, 21,557); 17+ (63, 55,188).
- 2,660 chunks, embedding_attempts_sum 459, zero API errors.

Production embedding provider: llama_cpp / Qwen3-Embedding-4B. Existing
inference already batches up to 32 texts and 32,768 characters. The prior
embedding_attempts counter counts each batch submission AND retries, so
it cannot distinguish normal batches from repeated failed submissions.
These observations identify the EMBEDDING STAGE as the dominant cost in
this rolling window, not yet Qwen/model/queue/retry/batch-size causal origin.

## Safe source-only extension

Within existing per-HTTP-request ContextVar trace:
- embedding_batches: first submission of each distinct inference batch,
  including one that fails finally;
- embedding_retries: actual subsequent submissions of the SAME batch,
  even if final error occurs;
- embedding_attempts: historical counter unchanged, set after a
  successful operation and potentially zero for failed ingestion.

Existing authenticated support/readiness numeric phase aggregates include
embedding_batches_sum, embedding_retries_sum and
requests_with_embedding_retries for global and existing size/concurrency/
chunk-count cohorts. Legacy in-memory samples missing these new keys
are accepted with zero additional counters. No source content, query,
provider error, URI, tenant ID, model response or secret is persisted.

Source-only integration must not alter model endpoints, batch size/char
budget, retry policy, vector dimensions/values, write transaction,
tenant isolation, SLO targets or private source handling.

## Remaining acceptance

After separately approved pinned deployment and rollback: independently
collect >=20 representative samples per relevant chunk-count cohort,
compare distinct batch count versus actual retry count on matched
observation windows, then test isolated synthetic model throughput
changes only if attribution supports them. Keep production RED until
real sustained ingest p95 <=10s / search p95 <=1.5s with error <=1%.
