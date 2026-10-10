# Refactor Phase 3 — retrieval, indexing, crawling and durable results (2026-10-10)

**Base:** Phase 2 / module-and-dependency audit PR #89, which itself depends on Phase 1 PR #88. Phase 3 deliberately preserves the public v1 HTTP API, collection embedding contracts, index revision SHA-256 format, Python SDK and Tender Agent integration.

## Source modules reviewed and modified

| Module | Finding | Change / acceptance gate |
|---|---|---|
| `storage.postgres.repository` | One per-chunk SELECT + UPSERT + flush for every embedding caused O(N) database round-trips | Add `upsert_embeddings` with batches of up to 128 and PostgreSQL `ON CONFLICT DO UPDATE`. Existing embedding identity and creation timestamp are not overwritten. Unit and real-PG checks cover repeated indexing. Existing `upsert_embedding` remains public and unchanged for callers needing it. |
| `api.service_mixins.retrieval` | N `session.get` calls to validate collection auth/contracts; revision check loaded full chunk texts twice; SHA-256 revision payload built as one large string | One select for all requested collection IDs, preserving per-collection authorization order; `load_only(chunk_id, content_hash)` for initial/final revision checks; streaming hash updates produce identical revision for all tested content and ordering. Bulk embedding write at ingest and rebuild. Reject inconsistent vector dimensions before writing. |
| `search.hybrid` | Untrusted/custom query expanders could return duplicate or unbounded variants, causing repeated embedding/backend calls and skewed weighted RRF | Post-filter case-insensitively and cap variants to requested limit; preserve first meaningful expansion and stage diagnostics. |
| `search.models` | Case-variant explicit search queries could defeat deduplication | Case-fold duplicate detection without lowercasing preserved query text. |
| `crawl.relevance` | Classification sorted all discovered targets just to count them; URL selection sorted all N targets despite max K needed | Count selectable directly; use heap-based `nsmallest(K, ...)` for probe and URL selection with matching deterministic score/index ordering. Stop normalizing irrelevant HTML text after bounded visible budget (title/H1 still processed). |
| `results.record_sets` | `load_result` decoded the same stored payload twice | Reuse one validated decoded record in both `load_record` and `load_result`, keeping identity checks and existing public return types. |

## Operational notes

- **No changes to active Mac mini production environments, launchd jobs, PostgreSQL production databases, or installed Python interpreters**. All integration tests use a temporary disposable database in the existing local pgvector PostgreSQL container, destroyed after testing.
- On 2026-10-10, reads from `/Volumes/ArvectumSSD` stalled (including plain file reads and `git status`), while metadata operations returned. Work moved to a fresh authenticated GitHub clone under `/Users/master/.cache/arvectum/dp-optimization-20261010` on the internal APFS disk. Do not assume that this proves a disk hardware fault. Investigate USB enclosure/cable/power/filesystem **without unmounting a production disk**.
- Heavy embedding-provider calls remain unbatched at the model endpoint. Bulk database writes reduce round-trips but do not by themselves cap a huge `embed_texts` request or total reindex memory. Future bounded embedding inference should preserve retry and atomic index activation.
- This iteration is targeted optimization, **not** a claim that all 158 modules were individually rewritten or fully benchmarked. See `docs/audits/module_inventory.csv` for module-by-module static screening.

## Verification

- Python 3.12, full Data Platform `pytest` suite, Python Ruff, JavaScript SDK tests, `uv lock --check --offline`.
- Real disposable PostgreSQL/pgvector suite verifies batched embedding INSERT count, stable embedding IDs, revision-only column projection, reindex idempotence, case-constrained authorization select count, error rollback and existing API contracts.
- Tender Agent consumer regression against fresh source clone using the unchanged Python 3.12 runtime environment.
- GitHub CI cross-version (3.11/3.12/3.13) and PostgreSQL jobs after branch push.

## Next prioritized actions

1. Bound inference-side embedding batches, retry envelopes and memory while preserving atomic index rebuild. Measure real vector latency and RAM with local models.
2. Investigate vector + lexical federation across multiple collections: the `PostgresSearchBackend` still does at least one query per collection and modality. Evaluate a multi-collection SQL plan after PostgreSQL `EXPLAIN (ANALYZE, BUFFERS)` and RRF parity tests.
3. Review P1 modules `api.service_mixins.billing`, `api.service_mixins.access`, `engine.html_records`, and `results.record_sets` for remaining hotspots with realistic load tests, authorization and redaction gates.
4. Revisit schema-only large modules (`storage.postgres.models`, `api.schemas`) after there is a concrete design boundary, not just for line-count reduction.
