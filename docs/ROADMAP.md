# Data Platform migration roadmap

Date: 2026-10-04

Legend: [x] done, [ ] ready/planned.

## Current state

- [x] Separate arvectum2/data-platform repository exists and mirrors to GitVerse.
- [x] Reuse audit of Discount Parser and Tender Agent completed.
- [x] Data Platform v1 product boundary fixed.
- [x] Search architecture fixed: scoped hybrid retrieval, evidence-first, PostgreSQL FTS + pgvector production backend.
- [x] Migration strategy fixed: compatibility/strangler migration, no big-bang rewrite.
- [x] Generic platform code has been promoted from Discount Parser into src/arvectum_data.
- [x] No blockers remain for the platform foundation.

## DP-FND-001 — repository/package foundation

Status: COMPLETE.

- [x] create pyproject.toml for arvectum-data / arvectum_data;
- [x] Python 3.11+ baseline;
- [x] ruff/pytest;
- [x] CI;
- [x] FastAPI service shell with /health;
- [x] ARVECTUM_DATA_ settings;
- [x] structured logging;
- [x] versioning/dev commands.

Gate: clean checkout -> install -> pytest -> /health = ok.

## DP-MIG-001 — promote generic extraction engine

Status: COMPLETE.

Source: discount-parser/arvectum_data.

- [x] move package with traceable source revision;
- [x] move focused tests/dp_engine platform coverage;
- [x] exclude product-coupled acceptance/parity tests from the platform suite;
- [x] preserve public Python imports;
- [x] reproduce acquisition/crawl/extraction/multi-record/persistence/review/execution behavior;
- [x] establish Data Platform repository as canonical implementation;
- [x] make Discount Parser consume arvectum-data pinned to canonical commit a591256;
- [x] run product regressions: 289 DP-engine tests and 634 full product tests passed;
- [x] remove duplicate only after acceptance; Discount Parser commit e0e3039.

Gate: promoted tests green and offline URL/HTML extraction works end-to-end without Discount Parser imports.

## DP-DOC-001 — generic document ingestion

Status: COMPLETE.

Reuse document_text_extractor, safe format handling and chunker from Tender Agent.

- [x] Resource, Document and Chunk contracts;
- [x] TXT/HTML/PDF/DOCX/XLSX extraction;
- [x] deterministic chunking;
- [x] content-hash/idempotency;
- [x] provenance from resource to chunk.

Gate: file/url -> Resource -> Document -> Chunk[] -> evidence without procurement models.

## DP-EMB-001 — embedding provider abstraction

Status: COMPLETE.

- [x] move provider protocol/errors;
- [x] deterministic hashing provider;
- [x] local embedding HTTP/llama provider;
- [x] decouple configuration from Tender Agent;
- [x] model/dimension identity;
- [x] batch interface;
- [x] health probe.

## DP-STORE-001 — canonical PostgreSQL schema

- [ ] Alembic;
- [ ] collections/resources/documents/records/chunks;
- [ ] provenance;
- [ ] actual vector(N) embedding storage;
- [ ] ingest/index runs;
- [ ] active index revision;
- [ ] collection isolation constraints.

Gate: empty PostgreSQL + pgvector -> migrate -> ingest/retrieve fixture.

## DP-LEX-001 — lexical backend

- [ ] LexicalIndex protocol;
- [ ] PostgreSQL FTS backend;
- [ ] Russian/English strategy;
- [ ] phrase/token/exact signals;
- [ ] metadata filters;
- [ ] in-memory test backend;
- [ ] lexical quality fixtures.

True BM25 is deferred until benchmarks show PostgreSQL FTS is insufficient.

## DP-VEC-001 — production pgvector backend

- [ ] VectorIndex protocol;
- [x] keep JSON/local backend for dev/tests;
- [ ] pgvector storage/query;
- [ ] collection-scoped vector query;
- [ ] measured HNSW/IVFFlat decision;
- [ ] model/dimension migration safety;
- [ ] PostgreSQL integration tests.

Gate: no production search path depends on JsonVectorStore.

## DP-SEARCH-001 — hybrid retrieval

- [ ] SearchQuery / SearchHit;
- [ ] lexical candidates;
- [ ] vector candidates;
- [ ] RRF fusion;
- [ ] metadata/security filters;
- [ ] stable tie breaking;
- [ ] evidence/provenance projection;
- [ ] optional product ranker hook;
- [ ] explain mode with component scores.

Gate: lexical and vector retrieval run simultaneously, collection isolation is enforced, every hit has evidence, and hybrid quality is benchmarked against both single retrievers.

## DP-API-001 — service v1

- [ ] collections API;
- [ ] ingest URL/document API;
- [ ] extraction API;
- [ ] search API;
- [ ] index jobs/status;
- [ ] request IDs/metrics;
- [ ] internal auth boundary;
- [ ] OpenAPI contract tests.

## DP-CONN-001 — connector SDK + generic web discovery

- [ ] discover/fetch protocols;
- [ ] registry;
- [ ] manual URL;
- [ ] sitemap/site crawler;
- [ ] generic web search;
- [ ] rate limit/retry;
- [ ] SSRF/private-network guard;
- [ ] health/status.

44-FZ/223-FZ/EIS stay product-specific initially.

## DP-INT-001 — Tender Agent migration

First production consumer.

- [ ] compatibility adapter from Tender RAG to Data Platform;
- [ ] migrate document extraction/chunking;
- [ ] migrate embedding/index path;
- [ ] replace vector-first/lexical-fallback with scoped hybrid search;
- [ ] preserve procurement filters/human-control boundaries;
- [ ] run current RAG/search regression and eval suites;
- [ ] compare citations/evidence;
- [ ] remove duplicate generic code after acceptance.

Gate: existing Tender Agent workflows remain green and no cross-tender leakage is possible.

## DP-INT-002 — Arvectum OS RAG migration

- [ ] inventory current knowledge/RAG interfaces;
- [ ] map sources to collections;
- [ ] ingest knowledge assets;
- [ ] switch retrieval to /v1/search;
- [ ] preserve access boundaries;
- [ ] evaluate evidence and latency.

## DP-INT-003 — Growth / SEO consumer

- [ ] arvectum.com site collection;
- [ ] app/product metadata collections;
- [ ] competitor/research collection;
- [ ] web discovery workflow;
- [ ] crawl/index change detection;
- [ ] Growth Agent Search API client;
- [ ] provenance-backed results.

## DP-OPS-001 — operational hardening

- [ ] idempotent ingest/index jobs;
- [ ] atomic index revision switch;
- [ ] retry/dead-letter policy;
- [ ] source/index freshness;
- [ ] ingest/search metrics;
- [ ] secret-free diagnostics;
- [ ] backup/restore;
- [ ] capacity guardrails.

## Post-v1 backlog

Only after three real consumers are integrated:

- [ ] entity resolution;
- [ ] entity graph/relations;
- [ ] benchmark-driven BM25 backend if needed;
- [ ] learned reranker;
- [ ] optional bounded LLM reranking;
- [ ] query expansion;
- [ ] distributed crawling;
- [ ] authorized federated cross-collection search;
- [ ] relevance feedback/evaluation pipeline.

## Definition of done

Every phase requires implementation in canonical data-platform, focused tests, affected-consumer regression verification, preserved provenance/security invariants, updated docs, a canonical commit, and duplicate removal only after consumer acceptance.

## Recommended execution order

~~~text
DP-FND-001
    ↓
DP-MIG-001
    ↓
DP-DOC-001 + DP-EMB-001
    ↓
DP-STORE-001
    ↓
DP-LEX-001 + DP-VEC-001
    ↓
DP-SEARCH-001
    ↓
DP-API-001 + DP-CONN-001
    ↓
DP-INT-001 Tender Agent
    ↓
DP-INT-002 Arvectum OS
    ↓
DP-INT-003 Growth/SEO
    ↓
DP-OPS-001
~~~

The first code task is deliberately not “write a new search engine”. It is to promote the mature extraction foundation into its canonical repository, then build the missing search layers around real consumer requirements.
