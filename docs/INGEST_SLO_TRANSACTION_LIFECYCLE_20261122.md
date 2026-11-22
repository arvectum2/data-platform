# Data Platform ingest transaction lifecycle — isolated structural regression (2026-11-22)

**Scope:** engineering improvement in draft [PR #134](https://github.com/arvectum2/data-platform/pull/134), linked to [issue #133](https://github.com/arvectum2/data-platform/issues/133), and the separately gated Tender Agent Core release. This **does not** establish that PostgreSQL connection occupancy caused the live ~20s ingest P95, nor that the latency is fixed. Nothing here is deployed.

## Mechanism confirmed by source and a synthetic SQLAlchemy test

The prior `_persist_and_index` implementation obtained a SQLAlchemy session, performed `session.get(CollectionRow)`, queried embedding IDs, staged `repo.persist_ingest` writes and **called `_embed_texts_with_retry` before ending the same transaction**. The database connection remained checked out during the external model call. Model inference is potentially slow or queued on a separate live `Qwen3-Embedding-4B` service, and holding connections during it is avoidable.

A minimal in-process test using *only SQLite* `QueuePool(pool_size=1, max_overflow=0)`, a synthetic collection and a mocked inference provider reproduced the original fact that a second independent connection could not be obtained during inference. No live database, original source text, model server or network was involved. The source change now makes the same test observe `pool.checkedout()==0` during inference and allows an independent second `SELECT 1`.

### Dedicated PostgreSQL17 integration regression

The additional CI-only `tests/api/test_ingest_tx_connection_postgres.py` uses a **unique generated synthetic collection** on the GitHub Actions ephemeral `pgvector/pgvector:pg17` service. The test creates a real SQLAlchemy Postgres QueuePool with `pool_size=1, max_overflow=0`, confirms a separate `SELECT 1` is available inside the mocked embedding call, validates actual vector persistence, idempotent repeated ingest, no source write after a mocked model outage, and deletes the synthetic collection after completion. **No real Qwen inference or production PostgreSQL is used.** The test now **skips outside GitHub Actions**, and within CI requires the **exact pinned synthetic username, password, database, PostgreSQL driver and 127.0.0.1:5432 port** from `.github/workflows/ci.yml`. It additionally verifies `current_database()` and `current_user` before any Alembic migration; a missing or altered CI fixture fails closed rather than falling through to arbitrary local/forwarded PostgreSQL. No real or ambiguous local DB may be targeted by this regression.

Initial source head `afec8db93ba19daa513e69fbffc3941c85ae6ee0`: protected GitHub CI `45047389966` **SUCCESS 5/5** including the PostgreSQL test, GitVerse `45047390052` SUCCESS. Additional guarded DB identity/startup-monitor changes at head `896d2c58c709c257dff13385e61988e1c0241570` passed 53 focused local tests, with the CI-only PG test skipped locally, and Ruff/compile PASS; exact protected head CI is independently required.

**Do not generalize that single-connection synthetic starvation to production:** the live connection-pool size, SQL wait events, actual concurrent load, per-inference wall/queue time and host readiness are not established by this test.

## Conservative draft change

The new implementation separates these concerns:

1. A **short read-only lookup session** validates collection/model contract and reads the previously available embedding IDs.
2. It closes that session, releasing its connection. The existing bounded `_embed_texts_with_retry` performs inference **with no database transaction open**. Any failed model request results in no ingest writes.
3. A **new write transaction** re-reads the collection and validates the same model contract, rechecks embedding coverage, and persists the resource/document/chunks/metadata plus missing embedding vectors **atomically in one commit**.
4. If another concurrent writer supplied a vector during inference, skip writing that vector and count it as already available; if a previously existing vector disappeared and no vector was computed, **fail closed** and ask for an explicit retry instead of falsely reporting complete indexing.
5. Preserve existing batch sizes, retry policy, source identifiers, dimension validation, vector similarity contract, PostgreSQL upsert semantics and the two-source/embedding consistency checks.

Exact focused isolated regressions added in `tests/test_ingest_slo_transaction_occupancy.py`: free SQL connection during model inference, concurrent vector inserted mid-flight, stable existing-vector reuse, unexpected disappearance, mid-flight model contract drift, synthetic inference exception and no-write behavior. These tests use mocked `DataRepository` writes and real local SQLAlchemy session lifecycle; they **do not** substitute for actual PostgreSQL integration CI.

## Verification and release boundary

On candidate code `fdea7e3246bc25365f4f1336b755afca9fbf5741`, **72 focused local pytest PASS**, Ruff PASS and Python syntax compilation PASS (SQLAlchemy lifecycle, mocked concurrency and model drift, Qwen guard/runner, batching, synthetic analyzer/producer). Protected GitHub CI **run 45046906695 SUCCESS 5/5**, including PostgreSQL integration, Python 3.11/3.12/3.13 and JavaScript SDK; GitVerse Mirror Health **run 45046906697 SUCCESS**. The final docs/checkpoint-only HEAD must also pass protected CI.

**Production measured before this patch:** DP readiness ingest P95 **20,152 ms / latest 256 samples** (target <=10,000ms), status RED. Nothing in this change modifies production processes, real documents, production DB, model settings, metadata, scheduled jobs, or other source-specific gates. The resource governor currently blocks any isolated extra Qwen load. The live model's queue-vs-inference contribution remains unknown.

Keep Data Platform issue #133 OPEN and PR #134 DRAFT pending independent workload-grounded attribution, PostgreSQL/tenant/source invariant acceptance and separately approved deployment. Keep Tender Agent Core/PRICE runtime rollout BLOCKED pending sustained live ingest SLO, independent model/source acceptance and Owner release decision.
