# Data Platform reuse audit

Date: 2026-10-04

## Audit scope

Audited live local checkouts:

| Repository | Revision | Role |
| --- | --- | --- |
| arvectum2/data-platform | 3701dda38c36 | target canonical platform repository |
| arvectum2/discount-parser | 4bde0909d18b | generic acquisition/extraction engine plus discount product |
| arvectum2/tender-agent | 3bbca3dc615b | procurement discovery, document ingestion, RAG and search |

The goal is not to merge repositories. The goal is to identify reusable infrastructure that should have one canonical implementation in data-platform.

## Executive finding

Data Platform does not start from zero.

discount-parser already contains a deliberately product-neutral package named arvectum_data. It has no dependency on discount-domain modules and is the strongest candidate for the first extraction.

tender-agent contains valuable reusable search/RAG components, but they are more coupled to procurement persistence (TenderRepository, procurement SQLAlchemy models and tender-specific API schemas). These should be migrated by interface extraction rather than copied wholesale.

There is also an important implementation gap: Tender Agent has a PostgreSQL pgvector extension migration and embedding metadata tables, but current retrieval uses JsonVectorStore. The production Data Platform must implement a real PostgreSQL vector backend instead of treating the current migration as a finished pgvector search implementation.

## Discount Parser audit

### Move to Data Platform with minimal or no behavioral change

| Source module | Decision | Notes |
| --- | --- | --- |
| arvectum_data/acquisition | MOVE | URL requests, static HTTP transport, render policy, Playwright renderer, bounded acquisition |
| arvectum_data/crawl | MOVE | canonical URL handling, link discovery, bounded crawler, relevance classification |
| arvectum_data/engine | MOVE | field specs, candidates/evidence, generic extraction, multi-record extraction, semantic HTML/JSON-LD discovery |
| arvectum_data/orchestration.py | MOVE | URL -> acquisition -> extraction -> recovery/learning pipeline |
| arvectum_data/profiles.py | MOVE | profile-aware provider and confirmation learning |
| arvectum_data/profile_lifecycle.py | MOVE | lifecycle/storage for learned site profiles |
| arvectum_data/recovery.py | MOVE | deterministic semantic-render recovery |
| arvectum_data/results | MOVE | durable result codecs/stores, revisions and review coordinator |
| arvectum_data/review_queue | MOVE | leases, reviewer identity, audit events, independent record review |
| arvectum_data/execution | MOVE | jobs, retries, checkpoints, executor |

These modules already expose platform concepts rather than discount concepts. They should keep the Python namespace arvectum_data to minimize downstream churn.

### Keep in Discount Parser

| Source module | Decision | Reason |
| --- | --- | --- |
| src/sources/adapters/* | KEEP | site/product-specific discount adapters |
| discount offer normalization/classification/publication | KEEP | business semantics belong to Discount Parser |
| Telegram publishing, XLSX correction UI | KEEP | product workflow |
| offer lifecycle and publication ledger | KEEP | product persistence/business rules |

### Extract later / selectively

| Source module | Decision | Notes |
| --- | --- | --- |
| src/sources/http.py | COMPARE then retire/adapter | overlaps Data Platform acquisition |
| src/sources/engine_runtime.py | ADAPT | product bridge to generic engine; useful as migration compatibility layer |
| parity telemetry/runtime | KEEP initially | current semantics protect generic-vs-legacy discount migration |

### Proven maturity

The generic engine series reached DP-ENGINE-019. Its live five-source acceptance preserved customer-safe output for all five production sources while generic extraction remained guarded by adapter parity. This is strong evidence that the extraction core is worth promoting rather than rewriting.

## Tender Agent audit

### Directly reusable after light decoupling

| Source module | Decision | Required change |
| --- | --- | --- |
| tender_research/document_text_extractor.py | MOVE/GENERALIZE | rename around generic documents; remove tender naming |
| tender_research/rag/chunker.py | MOVE | already generic text chunking |
| tender_research/rag/embeddings.py | MOVE/GENERALIZE | move provider contracts/config out of tender settings |
| tender_research/rag/vector_store.py | MOVE as dev backend | retain JSON backend for tests/local development |
| tender_research/browser/readability.py | MERGE | fold readable-text extraction into platform acquisition/document pipeline |
| tender_research/dedupe.py | PARTIAL MOVE | generic URL/content hashes; keep procurement identity rules out |
| tender_research/rate_limit.py | MOVE or replace | reconcile with acquisition throttling |

### Rewrite against generic interfaces

| Source module | Decision | Why |
| --- | --- | --- |
| tender_research/rag/retriever.py | REWRITE | depends on TenderRepository and JsonVectorStore; lexical search is fallback only |
| tender_research/rag/indexer.py | REWRITE/PORT | useful orchestration, procurement-specific persistence |
| tender_research/browser/requests_fetcher.py | RETIRE into acquisition | duplicates arvectum_data acquisition |
| tender_research/browser/playwright_fetcher.py | RETIRE/MERGE | duplicates platform renderer path |
| tender_research/search_provider.py | PROMOTE CONTRACT | basis for connector/search-provider protocol |
| providers/duckduckgo_html.py | MOVE as optional web connector | generic discovery, subject to provider stability |
| registry_discovery.py | KEEP domain coordinator | procurement semantics; consume platform contracts |

### Keep in Tender Agent

| Source module | Decision | Reason |
| --- | --- | --- |
| providers/public_44fz_search.py | KEEP initially | procurement/law-specific semantics |
| providers/public_223fz_search.py | KEEP initially | procurement/law-specific semantics |
| eis_loader.py, eis_real_loader.py | KEEP | EIS-specific domain integration |
| models.py, repository.py | KEEP | procurement data model |
| RAG analysis/report/history/job API | KEEP | product workflow and tender report semantics |
| supplier_search/* | KEEP | supplier/business-domain ranking and workflows |
| Tender Operator UI/routes | KEEP | product surface |

## Search engine gap audit

### What exists

- embedding providers;
- JSON vector store and cosine similarity;
- document chunking;
- scoped RAG retrieval;
- simple lexical fallback;
- generic web search provider;
- procurement-specific registry discovery;
- provenance/evidence primitives in arvectum_data;
- PostgreSQL infrastructure in Tender Agent;
- pgvector extension enablement in Tender Agent database migration.

### What does not yet exist as one engine

1. One canonical collection/resource/document/chunk model.
2. A real PostgreSQL vector search implementation using a vector column/index.
3. A first-class lexical index.
4. Parallel lexical + vector candidate generation.
5. Deterministic hybrid fusion/ranking.
6. Generic metadata filtering/facets.
7. A reusable /v1/search contract.
8. Versioned index state and reindex lifecycle.
9. Platform-level collection/tenant isolation.
10. Shared observability for ingest/index/search quality.
11. A product-neutral connector SDK and registry.

### Current lexical behavior

RagRetriever queries vectors first. Lexical scoring runs only if no vector hits are returned. The lexical score is deterministic substring/keyword matching, not BM25 and not a simultaneous hybrid candidate source.

Therefore current RAG retrieval is useful product functionality, but it is not the final Data Platform hybrid search engine.

### Current pgvector behavior

Tender Agent enables the PostgreSQL vector extension and stores embedding metadata, but the application search path persists/searches vectors through JsonVectorStore. There is no production PgVectorStore query path with vector distance operators in the audited code.

Data Platform should implement that capability explicitly and cover it with PostgreSQL integration tests.

## Reuse priorities

1. Promote arvectum_data unchanged first.
2. Introduce generic platform data/search contracts.
3. Port generic document extraction + chunking + embedding provider contracts.
4. Implement real PostgreSQL lexical/vector indexes.
5. Implement hybrid retrieval and evidence-bearing SearchHit.
6. Migrate Tender Agent RAG behind compatibility adapters.
7. Migrate Arvectum OS RAG/search.
8. Add Growth/SEO web discovery/indexing as the third consumer.

This order gives Data Platform three independent consumers before investing in speculative features such as entity graphs or LLM reranking.
