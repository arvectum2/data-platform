# Phase 7 — API modularization and bounded semantic record extraction

**Base:** PR #93; code developed/tested in a separate checkout on the internal Mac mini disk; no changes to live app/DB or SSH services.

## What changed

1. `engine.html_records`: DOM `_Node.text()` now caches compact subtree text, invalidated on incremental parser start/data changes. Repeated scoring, anchor detection and boundary assembly reuse the cache. The exact extracted record IDs, paths, evidence and metadata remain unchanged.
2. `engine.records`: structured `Sequence` records are consumed with `itertools.islice(max_records)` rather than eagerly copying all source records. JSON-LD field semantics are built once per page, rather than once per nested JSON object. The list of matched JSON-LD record objects is capped at `max_records`, with the original warning ordering and match decisions maintained. Attribute-record IDs are computed once rather than twice.
3. API routing: five 200–420 line nested route registration blocks split into topic-specific modules with facades preserving import compatibility and route registration order: billing/usage, collections/ingest, search/connectors, index/graph/feedback, research/answer/memory/refresh/extract. A few still-large groups were further split into entity/relations and research/answer. Auth dependencies, endpoint names, path order, schemas and error mapping are unchanged.
4. `api.app`: operation-name classifiers and exception-to-HTTP mapping extracted to small modules. Application factory, request metrics, header security and middleware control flow otherwise preserved.
5. Generated a full OpenAPI route manifest fixture of 55 paths; regression checks every method, operation ID, tag, public parameter, request content type, and response status. The entire OpenAPI JSON was independently compared byte-for-byte before/after extraction.

## Reproducible performance check

Run `PYTHONPATH=src python scripts/benchmark_html_records.py` (Python 3.12 on Mac mini). This uses in-memory synthetic offer HTML and compares stable SHA-256 fingerprints for records/IDs/attributes. Local median over three runs, ms:

| Cards | Before | After | Change |
|---|---:|---:|---:|
| 30 | 2.2 | 1.8 | ~18% |
| 100 | 7.4 | 5.9 | ~20% |
| 200 | 14.9 | 11.7 | ~21% |

**Caution:** microbenchmark measures warm local parsing CPU only. There is no end-to-end claim for remote fetching, OCR, PDF decoding, RAG or model inference.

## Verification

- HTML incremental parser invalidation and memoization tests; large structured source and 3,000-object JSON-LD truncation regressions.
- Exact original full OpenAPI JSON parity, plus committed route manifest across Python versions.
- Full non-PostgreSQL Data Platform suite, real temporary PostgreSQL + pgvector suite, Tender Agent cross-repo regression, JavaScript SDK, Ruff and lockfile integrity; GitHub Actions Python 3.11/3.12/3.13 and real DB jobs.
- `python scripts/audit_modules.py` regenerated all module priority assessments. Module count rises as registrars are split into independently testable topic modules; this is expected.

## Finalization and exclusions

Module-level AST inventory is a static review, **not** proof that all modules have been rewritten or load-tested. Large declarative schemas and ORM models were deliberately preserved to avoid accidental contract/schema drift. Production deployment requires review of SSD I/O stalls and an explicit controlled release. Remaining product-semantic design: immutable billing-period closure/late usage handling and crashed-worker payment recovery; these cannot responsibly be declared complete merely by rearranging code. The existing YooKassa provider uses an invoice-scoped idempotency key, but durable distributed recovery still needs a separate failure-injection exercise.
