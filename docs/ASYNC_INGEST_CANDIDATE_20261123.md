# Data Platform — durable asynchronous ingest candidate

Date: 2026-11-23. Owner approved the **two-mode product direction**, not a production rollout. PR #135 is review-only. Existing synchronous /v1/ingest/document and /v1/ingest/url remain unchanged.

## Contract

- POST /v1/ingest/jobs: authenticated multipart upload (collection_id, file, optional canonical_uri/title/pre_chunked; mandatory Idempotency-Key 8..128 safe characters). Returns HTTP 202 **only after the queue and source bytes commit in PostgreSQL**; 202 means queued, NOT indexed/searchable.
- GET /v1/ingest/jobs/{job_id}?collection_id=...: status queued/running/completed/dead_letter/cancelled. Completed results include resource/document IDs, chunk count and embedding count only; no source text, URL, filename, idempotency key or exception messages. Wrong collection returns 404.
- DELETE /v1/ingest/jobs/{job_id}?collection_id=...: cancel queued task and erase raw bytes. Running work is not safe to interrupt and returns 409.
- GET /v1/support/ingest-jobs: internal-key-protected aggregate-only SLI, separate from the historical synchronous ingest SLO. Exposes global active queue count/bytes/oldest age and recent 256 admissions' first-start queue-wait p95 and completed enqueue-to-searchable p95, error fraction and n>=20 sufficiency. No numeric background deadline is approved.

## Durability and failure behavior

- Migration 0014_async_ingest_jobs adds the PostgreSQL queue, with collection-scoped SHA-256 idempotency digest, request fingerprint, source bytes, state, attempt count, random lease token, lease expiry, and timestamps.
- Source bytes are stored in the same database as indexed source data until completed, cancelled, or dead-lettered, then set NULL. Database/backup privacy, access controls, and at-rest retention require independent operational review; backups may still retain prior bytes.
- Admission uses transaction-scoped advisory lock per collection to serialize job and byte quotas. Default limits: <=5 MB per upload, <=16 active jobs and <=20 MB queued/running source bytes per collection, plus <=64 active jobs and <=100 MB queued bytes **globally** (bounded configurable maxima). Conflicting idempotency request => 409; overload => 429.
- Explicit opt-in worker uses SELECT FOR UPDATE SKIP LOCKED to claim jobs, random exclusive lease token, 600s lease and 20s heartbeat. After crash, expiry permits replay; stale worker token cannot overwrite final state.
- Execution is **at least once** rather than exactly once; deterministic source IDs and existing ingest idempotency/skip-existing-embeddings make retries safe. Committed indexing precedes job COMPLETED status. On transient error, 3 attempts and bounded backoff; deterministic invalid input and exhausted attempts become dead_letter.
- Cancel/complete/dead_letter clears uploaded bytes from live job row. Error metadata stores exception type only, no source text.

## Feature flag and staging-only worker

Feature OFF by default: ARVECTUM_DATA_ASYNC_INGEST_ENABLED=false. No worker daemon, production migration, launchd change or model restart installed.

In a separately authorized isolated environment with ARVECTUM_DATA_ASYNC_INGEST_ENABLED=true and a verified disposable ARVECTUM_DATA_DATABASE_URL, worker entry points:
```
python -m arvectum_data.api.ingest_worker --allow-worker --once
python -m arvectum_data.api.ingest_worker --allow-worker --loop
```
Do not run these against production during candidate testing. The Qwen model stays in place; isolated E2E uses a synthetic hashing provider.

## Verified and unresolved

Isolated PG17/pgvector + HTTP E2E: migration and authenticated 202 receipt; idempotency replay/conflict; wrong-collection 404; queued cancellation/running 409; source searchable only after manual worker commit; full provenance; payload erased on terminal status; concurrent worker SKIP LOCKED single winner; lease expiry and stale-token protection; transient provider failure and retry; dead letter; per-collection backlog quota; authenticated background SLI; queued job surviving HTTP service restart; legacy sync search/index/ACL/SDK/recovery.

Not yet demonstrated: real Qwen 17+ chunk/format/concurrency p95, sustained production queue/worker capacity, fairness across collections, production interruption/rollback, backup retention, long-running lease heartbeats under resource pressure, user-facing job progress UI. No background p95 target or production activation is implied.

**Issue #133 remains OPEN. Production release HOLD.** The existing sync p95<=10s is not loosened. Staging migration and worker lifecycle and explicit owner release approval are prerequisites to any deployment.
