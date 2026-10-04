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

Status: COMPLETE.

- [x] Alembic;
- [x] collections/resources/documents/records/chunks;
- [x] provenance;
- [x] actual pgvector embedding storage with per-row dimension metadata;
- [x] ingest/index runs;
- [x] active index revision;
- [x] collection isolation constraints.

Gate: empty PostgreSQL + pgvector -> migrate -> ingest/retrieve fixture.

## DP-LEX-001 — lexical backend

Status: COMPLETE.

- [x] LexicalBackend protocol;
- [x] PostgreSQL FTS backend;
- [x] Russian/English/simple strategy with generated tsvector columns;
- [x] phrase/token FTS plus deterministic exact-phrase boost;
- [x] metadata filters with fail-closed whitelist;
- [x] in-memory test backend;
- [x] lexical acceptance fixtures including live PostgreSQL Russian search.

True BM25 is deferred until benchmarks show PostgreSQL FTS is insufficient.

## DP-VEC-001 — production pgvector backend

- [ ] VectorIndex protocol;
- [x] keep JSON/local backend for dev/tests;
- [x] pgvector storage/query;
- [x] collection-scoped vector query;
- [ ] measured HNSW/IVFFlat decision;
- [ ] model/dimension migration safety;
- [x] PostgreSQL integration tests.

Gate: no production search path depends on JsonVectorStore.

## DP-SEARCH-001 — hybrid retrieval

Status: COMPLETE (v1 deterministic hybrid).

- [x] SearchQuery / SearchHit;
- [x] lexical candidates;
- [x] vector candidates;
- [x] RRF fusion;
- [x] metadata/security filters;
- [x] stable tie breaking;
- [x] evidence/provenance projection;
- [x] optional product ranker hook;
- [x] component lexical/vector/fusion scores are always exposed for explainability.

Gate: lexical and vector retrieval run simultaneously, collection isolation is enforced, every hit has evidence, and hybrid quality is benchmarked against both single retrievers.

## DP-API-001 — service v1

Status: COMPLETE.

- [x] collections API;
- [x] ingest URL/document API;
- [x] extraction API;
- [x] search API;
- [x] durable index rebuild jobs/status with revision + metrics;
- [x] request IDs/basic service metrics;
- [x] internal API-key auth boundary;
- [x] OpenAPI contract tests.

## DP-CONN-001 — connector SDK + generic web discovery

Status: COMPLETE.

- [x] discover/fetch protocols;
- [x] registry;
- [x] manual URL;
- [x] sitemap-first discovery with bounded site-crawl fallback;
- [x] generic web search via product-neutral DuckDuckGo Lite connector;
- [x] rate limit/retry policy;
- [x] SSRF/private-network guard including redirect validation for connector HTTP;
- [x] connector health/status registry and /v1/connectors API;
- [x] /v1/discover service API.

44-FZ/223-FZ/EIS stay product-specific initially.

## DP-INT-001 — Tender Agent migration

First production consumer.

Status: PRODUCTION RUNTIME ACCEPTED; legacy removal pending.

Merged in Tender Agent PR #144 (cbd5275).

- [x] compatibility adapter from Tender RAG to Data Platform;
- [x] preserve Tender Agent as canonical owner of procurement chunks while using Data Platform pre-chunked ingestion;
- [x] migrate embedding/index path to Data Platform when the data_platform backend is selected;
- [x] replace vector-first/lexical-fallback retrieval with collection-scoped hybrid search;
- [x] preserve procurement filters, citation mapping and human-control boundaries;
- [x] run Tender Research regression suite and Tender Operator demo regressions;
- [x] verify live cross-repository ingest -> pgvector/FTS -> hybrid search -> Tender citation mapping;
- [x] fail closed when the current versioned Data Platform collection is absent/incomplete;
- [x] deploy/supervise the Data Platform service in the Tender runtime;
- [x] prepare/reindex real pilot tender(s) against the Data Platform backend;
- [x] switch Tender runtime to AI_CORP_RAG_RETRIEVAL_BACKEND=data_platform;
- [x] compare production retrieval quality, citations and latency against the legacy backend;
- [ ] remove duplicate legacy JSON-vector/generic retrieval code only after production acceptance.

Code gate passed: existing Tender Agent workflows and CI remain green, and normal retrieval is scoped to one deterministic versioned collection per tender.

Production runtime gate passed on the Mac mini on 2026-10-04. Data Platform is supervised by launchd on 127.0.0.1:8094, uses the dedicated arvectum_data database in the existing pgvector PostgreSQL runtime, and uses the local Qwen3-Embedding-4B embedding service on 127.0.0.1:8090. Pilot tender 0187200001726001304 was indexed as 60 resources / 60 documents / 60 chunks / 60 embeddings. Tender readiness became ready_for_analysis=true; a live hybrid query returned 5 mapped Tender hits in about 0.32 s, and retrieval-only analyze_tender fast mode completed 10 sections with 16 unique sources in about 1.5 s with no warnings or errors.

Legacy parity was rebuilt safely in an isolated temporary JSON-vector index from the same 60 current production chunks using the same Qwen3-Embedding-4B provider, without writing legacy embedding metadata back to production. Across five representative procurement queries, equal-weight Data Platform hybrid retrieval matched legacy semantic top-1 on 4/5 queries and averaged about 0.129 s versus about 0.196 s for legacy retrieval. The one mismatch was traced to a weak singleton PostgreSQL FTS hit over-promoted by equal-weight RRF. Data Platform therefore added generic per-request RRF weights while keeping its platform default at 1:1. Tender Agent PR #146 (4df33d7) selected a semantic-first profile lexical_weight=1, vector_weight=4. Production re-validation then matched the isolated legacy semantic top-1 on 5/5 queries, with Data Platform averaging about 0.159 s for the five-query run. Retrieval-only fast analysis still completed 10 sections with 16 unique sources in about 1.44 s with no warnings or errors.

## DP-INT-002 — Arvectum OS RAG migration

Status: CODE INTEGRATION MERGED AND RUNTIME DEPLOYED; synthetic production-service acceptance passed; real-data production acceptance pending.

- [x] inventory current knowledge/RAG interfaces;
- [x] map KnowledgeAssetRecord sources to deterministic versioned per-deal collections;
- [x] add explicit knowledge asset indexing through pre-chunked Data Platform ingest;
- [x] add bounded knowledge retrieval through /v1/search;
- [x] preserve deal-scoped access boundaries and canonical knowledge_asset_id mapping;
- [x] verify synthetic evidence mapping and latency against the production Data Platform service;
- [x] merge Tender Agent PR #147 (b40cb2b);
- [ ] run acceptance on the first real production KnowledgeAssetRecord set.

Tender Agent PR #147 was merged and deployed into the Mac mini runtime on 2026-10-04. Focused runtime tests passed 15/15 after deployment; both explicit knowledge endpoints fail closed with 404 not_found for a deal that has no knowledge assets.

The Arvectum OS database contained zero KnowledgeAssetRecord rows during the 2026-10-04 rollout, so the real-data gate cannot yet be closed. A live synthetic asset passed the full path (versioned deal collection -> pre-chunked ingest -> embedding -> hybrid search -> canonical asset mapping + source refs) with a representative search latency of about 0.18 s.

This integration is retrieval-only. It does not authorize autonomous M-049 Agent Registry or M-050 Prompt / Schema Library execution.

## DP-INT-003 — Growth / SEO consumer

Status: MERGED AND PRODUCTION-ACCEPTED.

- [x] arvectum.com site collection;
- [x] app/product metadata collections;
- [x] competitor/research collection;
- [x] web discovery workflow;
- [x] crawl/index change detection;
- [x] Growth Agent Search API client;
- [x] provenance-backed results.

Arvectum Site PR #2 (merge b6630c0) added the first-party site consumer. Production acceptance indexed 44 canonical pages into growth:arvectum-site:8f0e23f96d45b1b9: 44 resources / 44 documents / 158 chunks / 158 embeddings. Procurement intent ranked the tender-department page first; Photo Size intent ranked the product landing page first; every result carried canonical URL plus Data Platform resource/document/chunk evidence. A repeated index run detected no content changes and performed no writes.

DuckDuckGo production discovery was repaired in Data Platform commits f15b29a and f8dbcbb: anti-bot challenge pages are no longer treated as empty success, and the connector uses the working HTML endpoint with connector-specific browser-compatible headers. A live Growth discovery smoke returned 10 external results for photo resize iphone app.

Arvectum Site PR #3 (merge 4ff7ecc) added deterministic external research collections. Production acceptance discovered five URLs, indexed four successfully with one explicit fetch failure, and produced growth:research:df5477406a:9c4e55c17bb5200d with 4 resources / 4 documents / 53 chunks / 53 embeddings. Evidence-backed research search ranked App Store competitor pages first.

Arvectum Site PR #4 (merge 4d64899) added a separate product-metadata index derived only from public /tools/*/index.html landing pages. The current public product set contains Photo Size, indexed into growth:products:e93c4eb90b2b2e3a as 1 resource / 1 document / 1 chunk / 1 embedding. A product-intent search returned Photo Size with canonical URL and complete evidence. Site, research and product active-state files are independent.


## DP-OPS-001 — operational hardening

- [x] idempotent ingest/index jobs;
- [x] atomic index revision switch;
- [x] retry/dead-letter policy;
- [x] source/index freshness;
- [x] ingest/search metrics;
- [x] secret-free diagnostics;
- [x] backup/restore;
- [x] capacity guardrails.

Repeated ingest now preserves deterministic resource/document/chunk identities and skips already-existing embeddings for the same provider/model. Reindex revisions are deterministic over the collection chunk set plus embedding/search contract; a repeated unchanged rebuild returns the same durable completed job without recomputing embeddings. A rebuild failure or a collection change during rebuild fails closed and does not move active_index_revision.

Collection stats expose first/last source observation, latest embedding time, latest completed reindex time and the active revision. Global status exposes bounded object counts. Runtime operation counters now expose requests, errors, total latency and max latency for ingest, search, discovery and reindex. The status payload is deliberately secret-free: it contains no database URL, API key, query text, fetched URL or exception message. Production smoke on the Mac mini confirmed live search/discovery counters after restart. PostgreSQL backup/restore helpers now produce a custom-format dump, SHA-256 sidecar and manifest, refuse accidental production overwrite by default, and passed a live restore drill into a temporary database with exact row-count parity. Capacity is bounded by upload bytes, max chunks per ingest, max collections per search, existing search result limits and bounded crawl/discovery policies. Transient embedding-server outages use bounded exponential retry; exhausting retries moves a durable reindex job to dead_letter without changing the active revision. Re-running the same revision reuses that durable job and can recover it after the provider returns.

## Post-v1 backlog

Only after three real consumers are integrated:

- [x] entity resolution;
- [ ] entity graph/relations;
- [ ] benchmark-driven BM25 backend if needed;
- [ ] learned reranker;
- [ ] optional bounded LLM reranking;
- [ ] query expansion;
- [ ] distributed crawling;
- [x] authorized federated cross-collection search;
- [x] relevance evaluation pipeline;
- [x] relevance feedback capture loop.


Current benchmark evidence does not justify the deferred BM25 backend. On `lexical_exact_v1`, current hybrid retrieval scored top-1 1.00 / MRR 1.00, compared with vector-only 0.60 / 0.80 and PostgreSQL FTS lexical-only 0.80 / 0.90. BM25 remains backlog-only until a larger benchmark shows a repeatable lexical gap.

The first post-v1 evaluation harness is consumer-neutral and runs frozen JSON benchmarks against the HTTP search contract. It reports top-1 accuracy, MRR, hit-rate@3/@5, recall@5 and latency p50/p95/max, with CI-style minimum thresholds. Production snapshot production_acceptance_v1 contains nine accepted Tender/Growth cases; its first run on 2026-10-04 scored top-1=1.0, MRR=1.0, hit-rate@5=1.0 and mean recall@5=1.0, with about 103 ms p50 and 214 ms p95 latency. Relevance feedback capture is now durable and consumer-neutral: consumers can attach relevant / partially_relevant / not_relevant judgments to validated search-hit identities, list judgments, and inspect per-collection label summaries. Raw query text is not stored; only SHA-256 query_hash is persisted. Automatic learning/reranking from this feedback remains deliberately out of scope.

Entity resolution is now deterministic and ambiguity-safe: exact normalized aliases return resolved, ambiguous, or unresolved; the platform never auto-merges multiple candidates. Canonical names are stored as name aliases, while stable identifiers can use separate alias kinds.

Federated cross-collection search now requires a consumer-scoped key. Collections can restrict access with allowed_consumers; protected single-collection search uses the same verified consumer identity. Authorization is fail-closed: an unauthorized collection returns 403 and is never silently omitted from a federated result set.

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
