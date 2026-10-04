# Migration source ledger

## DP-MIG-001 — Discount Parser generic engine

- source repository: arvectum2/discount-parser
- source revision: 4bde0909d18b
- source path: arvectum_data/
- destination package: src/arvectum_data/
- initial promoted focused tests: 18 product-independent tests from tests/dp_engine/

Product-coupled acceptance/parity tests intentionally remain in Discount Parser:

- test_engine_acceptance.py
- test_engine_acceptance_cli.py
- test_live_semantic_remediation.py
- test_production_source_runtime.py
- test_source_parity_telemetry.py

Those tests depend on Discount Parser source adapters, configuration, parity telemetry or CLI and therefore validate the consumer integration rather than the neutral platform package.


### Consumer cutover

- Data Platform canonical commit: a591256f50a21b8618639129eccb15eb214204d5
- Discount Parser cutover commit: e0e303999e8fb1c2d6665f9013d3ad0d7ea1c2d7
- dependency form: pinned public Git VCS dependency
- focused consumer verification: 289 tests passed
- full Discount Parser regression: 634 tests passed
- vendored arvectum_data package removed from Discount Parser after acceptance


## DP-DOC-001 / DP-EMB-001 — Tender Agent reusable RAG primitives

- source repository: arvectum2/tender-agent
- source revision: 3bbca3dc615baedefe645c0ed0036d6534d12998
- source modules promoted/generalized:
  - src/tender_research/document_text_extractor.py
  - src/tender_research/rag/chunker.py
  - src/tender_research/rag/embeddings.py
  - src/tender_research/rag/vector_store.py
- product coupling removed: TenderResearchConfig and TenderRepository are not imported by Data Platform
- platform additions:
  - Resource / Document / Chunk / Provenance contracts
  - deterministic file and URL ingestion
  - collection identity on resources
  - generic EmbeddingConfig
  - local JSON vector backend retained for test/dev
- verification at promotion: 254 Data Platform tests passed on Python 3.11


## DP-STORE-001 — canonical PostgreSQL storage

- implementation is native to Data Platform
- PostgreSQL schema: collections, resources, documents, records, chunks, embeddings, provenance and pipeline runs
- pgvector-python baseline verified against current 0.5.x SQLAlchemy API
- local live acceptance used an isolated temporary database in the existing pgvector PostgreSQL container
- acceptance path: Alembic upgrade -> file ingest -> chunk persistence -> hashing embeddings -> pgvector cosine search
- collection isolation verified by a negative cross-collection search
- temporary acceptance database removed after the test


## DP-LEX-001 / DP-SEARCH-001 — universal search engine v1

- PostgreSQL FTS uses generated stored tsvector columns for simple, Russian and English configurations.
- Each FTS column has a GIN index.
- lexical ranking uses ts_rank_cd plus a deterministic exact-phrase boost.
- vector retrieval remains collection-scoped and supports the same filter whitelist.
- hybrid retrieval executes lexical and vector candidate generation independently and fuses them with reciprocal-rank fusion (RRF).
- SearchHit always exposes lexical, vector and fusion component scores plus source evidence.
- an optional product ranker hook runs only after generic fusion.
- normal SearchQuery requires at least one explicit collection.
- live acceptance used an isolated temporary PostgreSQL database and verified Russian lexical retrieval, pgvector retrieval, hybrid fusion, source filtering and negative cross-collection isolation.
