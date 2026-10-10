# Data Platform — cross-layer refactoring acceptance (2026-10-09)

## Scope and boundaries

- Canonical package: `arvectum-data` **0.6.0**, Python 3.11+; Python consumer SDK **0.3.0**; HTTP contract **v1**.
- Reviewed package boundaries across the approximately 158 Python source modules. The already-landed API/service decomposition is retained; this pass fixes the upload/extraction/retrieval and consumer-contract defects it exposed. It is not a second wholesale rewrite.
- Tender Agent remains a consumer. Procurement decisions, legal rules, price/bid ranking, tender-source interpretation, report writing and local domain RAG projections are **not** moved into Data Platform.
- No schema/migration changes, SDK major-version change, production database writes, launchd restart or live model profile changes.

## Implemented changes

1. **Single byte/file ingestion path.** Added `documents.ingest_bytes()` and reused `ingest_file()` from both HTTP process/ingest service methods. One bounded temporary lifecycle covers legacy converters. Resources, documents and chunks uniformly retain the logical upload filename, stable source URI, content hash and IDs; no temporary path leaks into source metadata.
2. **Complete native PDF traversal and explicit OCR budget.** Parse native text from all readable pages rather than silently cutting a document after the tenth. Expensive OCR remains bounded to the first 10 *eligible* pages by default. Preserve page assessments and report `pdf_page_count`, `text_truncated`, `ocr.skipped_page_numbers`, `ocr.unresolved_page_numbers`, and `extraction_warnings` in optional metadata. Blank scanned pages beyond OCR budget are **not** presented as successfully extracted; consumer review/escalation is required.
3. **Russian text and OOXML safety.** Detect UTF-8 BOM, UTF-16, UTF-32, CP1251 and KOI8-R; use conservative Russian-trigram evidence when CP1251/KOI8-R are both syntactically valid. Preserve the existing CP1251 fallback for ambiguous bytes. Bound Office ZIP member/total expansion and extreme compression ratios before DOCX/XLSX decoding.
4. **Searchability of short sources.** A short nonblank document becomes one content-hashed chunk rather than a successful ingestion with zero searchable evidence. The configured minimum remains a filter for small *tails* of longer sources. Chunk source coordinates remain offsets into `normalize_text`, not original PDF/Office bytes.
5. **API and SDK consistency.** Suppress absent optional `tenant_id` in created collection policies (instead of adding `null`). Python SDK has a single transport error boundary and typed authentication, unavailability, rate-limit and conflict subclasses of `DataPlatformError`; status, path and method are preserved. The `.retryable` flag is only an advisory signal, never authorization to retry writes blindly.
6. **Repaired test seams after service decomposition.** Integration/evaluation harnesses patch the actual URL-ingest implementation in `service_mixins.memory_sync` rather than a removed private import in `api.service`. Removed duplication between model-powered extraction provider selection paths.

## Verification / reproducibility

From the refactor worktree, with the project sources and SDK source on `PYTHONPATH`:

```shell
PYTHONPATH="$PWD/src:$PWD/sdk/python/src" python -m pytest -q
python -m ruff check src tests sdk/python/src
node --test tests/sdk/javascript_client.test.mjs
```

PostgreSQL acceptance also passed **20** tests (`pytest -q -m postgres`) against a disposable database created in the existing PostgreSQL container and dropped after completion. It exercised migrations, Postgres/pgvector search, authentication/tenancy, encrypted connector credentials, refresh, billing and evaluation paths without changing the production database.

Tender Agent cross-repository consumer regression passed **59** tests using the Data Platform and Python SDK sources from this worktree (RAG, boundary, indexing recovery, authentication, shared document processing and connector text extraction).

The ordinary test suite, Ruff, and JavaScript SDK passed as well. Existing FastAPI/Starlette deprecation warning is third-party compatibility noise; no new test warnings were introduced. Live external OCR/VLM/LLM throughput/accuracy, provider availability and production deployment are deliberately **not** claimed by this code-only acceptance.

## Non-regression requirements

- Keep the v1 wire schema and SDK 0.3.x import surface backward compatible.
- Do not silently drop scanned pages exceeding the OCR page budget; inspect metadata and request a bounded follow-up/review rather than inventing text.
- Keep exact chunk text/hash and normalized coordinate semantics for Tender Agent evidence.
- Tenant restrictions and connector credentials remain fail-closed.
- Preserve the running Mac mini profiles; deploy or change model runtimes only in separately accepted operations work.
