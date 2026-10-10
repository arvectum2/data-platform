# Refactor Phase 4 — bounded model inference, federated PostgreSQL retrieval, tenant identity reuse

**Base:** PR #90 (after Phase 1 and Phase 2, merged into `main` on GitHub); Phase 4 is a separate reviewable branch and was not deployed to the live Mac mini runtime.

## Implemented modules and contracts

| Module | Change | Compatibility / risk control |
|---|---|---|
| `api.config` | Add `embedding_inference_batch_size=32` (1–512), `embedding_inference_batch_chars=32768` (1024–1000000) environment-configurable settings | The source chunk is **never truncated**, even if it individually exceeds the character budget |
| `api.service_mixins.retrieval` | Bound calls to `embed_texts`, retry only a failed batch, combine outputs in original order; early contract validation on dimension/count; reuse resolved tenant identity | Caller still persists **only after all embedding batches succeed**; ingestion/rebuild transaction semantics and response schemas preserved. `embedding_attempts` now reports total provider calls when more than one batch is required |
| `storage.postgres.repository` | New `search_vectors_collections` and `search_lexical_collections` queries scoped by authorized collection IDs | Global top-K preserves the prior merge of per-collection top-K rankings; all search filter conditions are retained. Group lexical SQL by configured PostgreSQL language vector (`russian`, `english`, `simple`) |
| `search.postgres` | Use new multi-collection repository methods when searching >=2 collections; preserve single-collection adapter | Stable `BackendHit` contract, `collection_id` metadata, rank sorting, public search API |
| `api.service_mixins.access` | Tenant quota resolution returns request-scoped tenant identity for reuse in collection policy checks | **No global tenant cache** or cross-request authorization caching; allowed-consumer checks remain enforced |

## Measurable work reduction (statement counts, not latency benchmarks)

- **Vector retrieval:** N SQL queries for N collections becomes **one ranked vector SELECT** for the same query/filters.
- **Lexical retrieval:** N queries for N collections becomes **one SELECT per distinct language** (up to 3 groups). In normal Data Platform service calls, collection languages come from the already-authorized collection rows without a second metadata SELECT.
- **Inference:** a request with 100 embeddings is now processed as up to four 32-item calls; the character budget can split them further, preventing unbounded single model-server requests. Total result vectors may still occupy memory until index persistence, so this is inference-call bounding, not full streaming.
- **Tenant validation:** a consumer identity is resolved once per search request, and reused for all collection access policies.

## Verification gates

1. Unit tests for size/character limits, no truncation, per-batch retry, dimensional consistency, quota and tenant access.
2. Disposable PostgreSQL/pgvector parity tests compare full `chunk_id`, score and collection identity from the old vs new lexical/vector search (top 1/5/15), including mixed-language collections.
3. Separate filter isolation tests ensure `resource_id` cannot leak results from another collection.
4. Real PostgreSQL rollback test forces a second embedding batch to fail after one succeeded; no chunks survive the failed ingestion transaction.
5. Full Data Platform Python 3.12 tests, consumer Tender Agent regressions, JS SDK, Ruff and GitHub Actions CI Python 3.11/3.12/3.13 + pgvector checks.

## Follow-up

- Profile actual PostgreSQL execution plans (`EXPLAIN (ANALYZE, BUFFERS)`) under production-scale synthetic data; global vector top-K queries may require new indexes/partitioning to outperform the former per-collection plan at scale.
- Benchmark real embedding server peak RAM, input tokens, throughput and OCR/complex Russian tender-document quality across realistic corpora. Character limits are a transport guard, not exact tokenizer-based context budgeting.
- Refactor large billing and access modules only after locking invoice idempotency, isolation, data correctness and backward-compatible API test fixtures. No speculative schema rewrite in this phase.
- Resolve USB SSD read stalls before any deployment. No active service or production database was changed in this phase.
