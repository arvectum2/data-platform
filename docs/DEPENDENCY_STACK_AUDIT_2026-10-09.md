# Data Platform — dependency and Python runtime review (2026-10-09)

## Python: deployment versus compatibility testing

The three CI versions **3.11, 3.12, 3.13** are *separate GitHub Actions test jobs*, not three instances of Data Platform on the Mac mini. The Mac mini's **live Data Platform server** (`/Users/master/arvectum-runtime/data-platform/.venv`) and **live reranker** (`.../data-platform-reranker/.venv`) both already use **CPython 3.12.14**. The Tender Agent development repository also uses CPython 3.12.14; the main Data Platform repository's older *development* venv uses 3.11.16. Additional Python 3.14 apps run separately on the host and are outside this project's scope.

**Decision:** `.python-version` selects **3.12** for this repository's new development environments. Keep `requires-python >=3.11` and the 3.11/3.12/3.13 CI matrix for backward compatibility. No runtime restart, Python uninstallation or environment reuse across applications is necessary. A future move to 3.12-only compatibility requires a separate SDK/support decision.

## Direct libraries, why they exist, and the change decision

| Dependency | Purpose | Policy |
|---|---|---|
| SQLAlchemy + Alembic | PostgreSQL ORM and migrations | Retain; no custom DB framework. Move schema changes through migration tests, not runtime startup |
| psycopg[binary] + pgvector | PostgreSQL access, vectors | Retain portable binary until native `libpq` is verified on macOS and deployment images; local wheel ~17 MB for `psycopg-binary` |
| FastAPI + uvicorn + python-multipart | API service and document upload | Retain service compatibility. Reassess a separate server install extra once deployments are migrated |
| cryptography | Encrypted connector credentials | Retain (security-critical, ~21 MB); do **not** replace with hand-written cryptography |
| pydantic-settings | Typed environment configuration | Retain (existing Pydantic models and FastAPI ecosystem) |
| pypdf | PDF extraction and OCR page assessment | Retain; no library switch without Russian document benchmark and provenance equivalence |
| openpyxl + xlrd | XLSX and legacy XLS | Retain; required for real legacy procurement attachments |
| httpx + pytest + ruff (dev extra) | Tests and static checks | Keep out of production-only environments |
| Playwright (browser extra) | JS-rendered acquisition | Keep optional: browser installation/download can be expensive |
| sentence-transformers (rerank extra) | Cross-encoder reranking | Keep isolated behind HTTP reranker service and optional extras; **not in the base API venv** |

**Measured installed environment sizes on Mac mini (approximate):** Data Platform server venv **85 MB**, Data Platform development venv **119 MB**, optional benchmark reranker venv **870 MB**, running reranker venv **871 MB**. Heavy neural model weights/caches are outside these venv totals and must be audited separately before deletion. They are not evidence of three Python versions being used by one service.

`uv.lock` had drifted: it identified Data Platform as **0.5.0** despite `pyproject.toml` declaring **0.6.0**, and omitted mandatory `cryptography`/`xlrd` plus the optional reranker extra. Re-resolved **offline** and added deterministic `scripts/check_dependency_lock.py` with a regression test. Note that a lockfile may contain optional ML packages even when the lightweight runtime **does not install** them.

## Deployment guidance

- On Mac mini and future VPS use a dedicated Python **3.12** virtual environment per deployed service, not the global Homebrew Python.
- Use `uv sync --frozen --no-dev` for the base service; install `[rerank]` **only** in its separate environment. Use `uv sync --frozen --extra dev` for developer checks.
- Do not remove or merge active launchd/venv directories solely because two services share a Python version; their dependencies and update cycles differ.
- CI should continue unit/static/consumer-compatibility tests; execute PostgreSQL integration tests against an **isolated disposable database**, never a production database.
- Evaluate native libpq, fewer API extras, and ML model alternatives only with smoke tests, image portability checks, OCR/RAG quality gates, and runtime latency/memory benchmarks.
- Before upgrading externally sourced libraries, run vulnerability/license audits, `uv lock --check`, consumer SDK checks and frozen Russian-document evaluations. Upgrading to the newest version is not automatically an optimization.

## Module-by-module audit scope

See `docs/audits/module_inventory.csv` for all individual modules and `docs/audits/module_inventory.md` for prioritization. Static analysis is a **screening stage**; P1/P2 findings remain a queue for targeted refactors after correctness, contract and benchmark gates. `api.schemas` and `storage.postgres.models` are intentionally long schema declarations, not automatically pathological runtime code.

## Automated safeguards in this change

- CI runs `scripts/check_dependency_lock.py` against project + lock metadata on Python 3.11, 3.12 and 3.13.
- A separate Python 3.12 CI job provisions a disposable `pgvector/pgvector:pg17` PostgreSQL service and executes the previously skipped PostgreSQL integration suite; it does not touch Mac mini or production data.
- The root `arvectum_data` namespace is now lazily exported, retaining all 126 public names. Locally measured cold import fell from ~41 ms to ~3 ms on Python 3.11 without changing public symbol identity.
- `export_collection` now batch-prefetches related documents, chunks, records and provenance. For six resources, the SQL statement budget is at most 7 instead of a query count growing with resource/document count. Metadata-only mode defers heavy text/data columns and preserves response shape/pagination. Tested against disposable PostgreSQL.
