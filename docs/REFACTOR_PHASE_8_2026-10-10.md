# Phase 8 — hybrid search responsibility split / final source consolidation

The `HybridSearchEngine.search` implementation formerly mixed query expansion, deduplication, retrieval calls, RRF fusion, product post-ranking and rerank diagnostic reporting in one ~224-line method. It now delegates query expansion to `_prepare_queries`; the existing error-isolation, explicit/query-expansion order, bounded limits, diagnostic metadata and weighted-RRF semantics are preserved. No new model calls or SQL reads have been introduced.

Regression tests cover lexical-only, vector-only, hybrid weighted RRF, deduplication, unavailable expanders, failed-open errors (including diagnostics privacy), and existing rerank diagnostics. The complete Data Platform suite, PostgreSQL/pgvector suite, Tender Agent source-compatibility suite, JavaScript SDK and GitHub CI on Python 3.11–3.13 are acceptance gates.

`python scripts/audit_modules.py` now inventories **177 Python source modules** following earlier route decomposition, with P1 static size/branch flags reduced from 18 to 11. Remaining P1 modules are large by *aggregate size* but have bounded inner functions; several are declarative API schema and SQLAlchemy model definitions. Their labels are **not** evidence of concrete performance faults, and they have not all been rewritten. The per-module CSV is a risk-index and code review worklist, not a blanket claim of exhaustive runtime validation.

Deployment is deliberately separate from source merge. Active Mac mini services should not be hot-replaced until SSD access and rollback are verified. Additional product-design changes—closed billing periods, late usage and durable external-payment crash recovery—must be specified and acceptance-tested rather than silently changed in a refactor.
