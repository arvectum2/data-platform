# Data Platform migration roadmap

Date: 2026-10-04

Legend: [x] done, [ ] ready/planned.

## Current state

- [x] Separate arvectum2/data-platform repository exists and mirrors to GitVerse.
- [x] Reuse audit of Discount Parser and Tender Agent completed.
- [x] Data Platform v1 product boundary fixed.
- [x] Search architecture fixed: scoped hybrid retrieval, evidence-first, PostgreSQL FTS + pgvector production backend.
- [x] Migration strategy fixed: compatibility/strangler migration, no big-bang rewrite.
- [ ] Platform code has not yet been promoted into this repository.
- [ ] No blockers for starting foundation extraction.

## DP-FND-001 — repository/package foundation

Status: READY — next task.

- [ ] create pyproject.toml for arvectum-data / arvectum_data;
- [ ] Python 3.11+ baseline;
- [ ] ruff/pytest;
- [ ] CI;
- [ ] FastAPI service shell with /health;
- [ ] ARVECTUM_DATA_ settings;
- [ ] structured logging;
- [ ] versioning/dev commands.

Gate: clean checkout -> install -> pytest -> /health = ok.

## DP-MIG-001 — promote generic extraction engine

Source: discount-parser/arvectum_data.

- [ ] move package with traceable source revision;
- [ ] move focused tests/dp_engine platform coverage;
- [ ] remove test imports that initialize Discount Parser product modules;
- [ ] preserve public Python imports;
- [ ] reproduce acquisition/crawl/extraction/multi-record/persistence/review/execution behavior;
- [ ] establish Data Platform as canonical implementation;
- [ ] make Discount Parser consume arvectum-data;
- [ ] run product regressions;
- [ ] remove duplicate only after acceptance.

Gate: promoted tests green and offline URL/HTML extraction works end-to-end without Discount Parser imports.

## DP-DOC-001 — generic document ingestion

Reuse document_text_extractor, safe format handling and chunker from Tender Agent.

- [ ] Resource, Document and Chunk contracts;
- [ ] TXT/HTML/PDF/DOCX/XLSX extraction;
- [ ] deterministic chunking;
- [ ] content-hash/idempotency;
- [ ] provenance from resource to chunk.

Gate: file/url -> Resource -> Document -> Chunk[] -> evidence without procurement models.

## DP-EMB-001 — embedding provider abstraction

- [ ] move provider protocol/errors;
- [ ] deterministic hashing provider;
- [ ] local embedding HTTP/llama provider;
- [ ] decouple configuration from Tender Agent;
- [ ] model/dimension identity;
- [ ] batch interface;
- [ ] health probe.

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
- [ ] keep JSON/local backend for dev/tests;
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
