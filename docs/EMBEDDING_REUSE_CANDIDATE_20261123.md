# Issue #133 — bounded same-collection embedding reuse candidate

Date: 2026-11-23. Deployment: **NOT performed**. Candidate code only in
PR #135, default behavior unchanged. No production model, database, scheduler,
launchd or Tender Agent code changes. No new vector index or migration.

## Evidentiary rationale

- Read-only SQL sample of latest **1,500** persisted chunk rows drawn from
  two real production collections: **61** exact SHA-256 content-hash repeats
  *within the same collection* (**4.07%** of sampled chunks). This is a
  bounded historical sample, not a universal corpus duplicate rate or a
  predicted achieved cache-hit ratio. Matching source text is canonicalized
  and hashed by the established chunker.
- Owner-approved isolated real Qwen3-Embedding-4B + PostgreSQL17 stage
  previously measured 20 synthetic ingests, p95 9050ms, embedding phase
  p95 8952ms, with the 27-chunk request taking 24079ms. Text extraction and
  SQL overhead were low. Large **unique** documents still dominate latency.
- Therefore reusing a previously embedded chunk can save one model invocation
  for repeat content, but a 4% duplicate rate is **not** a solution for the
  sustained production ingest p95 ~21s vs the <=10s acceptance target.
  A sample duplicate is only a *possible* cache hit: a completed prior
  source must still be in this one process within the 300-second TTL.

## Implemented candidate behavior

- New `EmbeddingReuseCache`, capacity bounded by `embedding_reuse_cache_entries`
  **0..512**, default **0 = disabled**. A recommended first *staging-only*
  test value is 64; no production setting has been changed. TTL 300 seconds.
- In-process memory only. Keys contain the collection ID, **identity of the
  actual provider object**, provider/model names, dimension, and SHA-256
  chunk hash; values are immutable tuples of vector floats. The cache stores
  **no** source text, filename, canonical URI, resource/document ID, tenant
  secrets, or request payload. This does not share vectors across collections.
- Retrieved vectors are copied before use. The cache retains a reference
  to its active provider and immediately invalidates all entries on a
  provider-object swap; recycled Python `id()` values cannot resurrect vectors
  from an old provider. Provider dimension must be known;
  empty/inconsistent vectors do not enter the cache. An alias/provider swap
  under a different object is isolated; expiry limits old entries.
- Normal SQL read-only embedding lookup and post-inference SQL
  **revalidation** remain in place. New document chunk rows and their reused
  vectors are still written under one transaction with unchanged provenance.
  Cached entries are published only **after successful SQL commit**, never
  after a partial write, failed model call, or rollback.
- No change to synchronous `/v1/ingest` response type, search contract,
  requested provider, model, 2560-dimensional Qwen index, text normalization,
  idempotency, authorization, embedding failure retry semantics or SLO.

## Verified candidate acceptance

- Unit: default-off; invalid capacity; same collection hit; cross-collection
  miss; different provider object/model/dimension miss; unknown dimension
  refusal; incorrect vector dimension rejection; bounded LRU, TTL expiry,
  copy-on-read and concurrent-access safety; no text retained in cache.
- Actual isolated PG17 + hashing HTTP E2E: two separate resources with the
  same normalized text in the same collection. First full ingest embeds;
  second **writes its own vector and resource provenance with 0 additional
  embedding attempts**. Same text in a different collection performs an
  actual model call, confirming isolation. SDK, ACL, migration, retrieval,
  source rollback and recovery remain valid.
- Synthetic slow-provider test: first independent document triggers a
  forced **40ms** embedding delay; second identical text from a new source
  in the same collection completes without an embedding-provider invocation.
  This is a deterministic skip/cost demonstration, **not** a measured Qwen
  speedup or a statistically significant production p95 improvement.
- The complete test suite, Ruff and exact-head CI are required before
  declaring this ready for review.

## Release decision

**READY FOR CANDIDATE REVIEW only**, not production. Because only a minority
of chunks appear repeated, keep the feature disabled by default. A meaningful
production SLO reduction will require separately benchmarked improvements
for large unique inputs: Qwen inference throughput, 8-chunk batching,
one-slot Qwen queue contention, possible lower-weight-precision Qwen3-4B
with unchanged 2560d dimensionality *only after quality and model compatibility
checks*. As of this checkpoint, available on-disk embedding GGUF is
**Qwen3-Embedding-4B-Q8_0**; no alternate model is running. Current high swap
precludes launching a second model; do not bypass the governor.

Issue #133 OPEN and production HOLD. Rollout requires independent owner review,
controlled model-quality evaluation, real input-size and concurrency cohorts,
and sustained >=20 real-model representative observations with p95<=10s,
error rate<=1% and unchanged retrieval relevance/ACL/source fidelity.
