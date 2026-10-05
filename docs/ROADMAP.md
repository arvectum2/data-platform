# Data Platform migration roadmap

Date: 2026-10-05

Legend: [x] done, [ ] ready/planned.

## Current state

- [x] Separate arvectum2/data-platform repository exists and mirrors to GitVerse.
- [x] Reuse audit of Discount Parser and Tender Agent completed.
- [x] Data Platform v1 product boundary fixed.
- [x] Search architecture fixed: scoped hybrid retrieval, evidence-first, PostgreSQL FTS + pgvector production backend.
- [x] Migration strategy fixed: compatibility/strangler migration, no big-bang rewrite.
- [x] Generic platform code has been promoted from Discount Parser into src/arvectum_data.
- [x] No blockers remain for the platform foundation.
- [x] Versioned consumer contract 1.x plus lightweight Python/JavaScript SDKs are the canonical cross-product boundary.
- [x] Tender Agent no longer owns a duplicate generic RAG/document-processing implementation; procurement presets, namespaces and evidence mapping remain consumer-owned.

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

Status: COMPLETE.

- [x] VectorIndex protocol;
- [x] keep JSON/local backend for dev/tests;
- [x] pgvector storage/query;
- [x] collection-scoped vector query;
- [x] measured HNSW/IVFFlat decision;
- [x] model/dimension migration safety;
- [x] PostgreSQL integration tests.

Measured on 2026-10-05 against 697 real Qwen3-Embedding-4B vectors at 2560
dimensions: exact float32 search remained below 3.4 ms p95 with 100% recall@10,
while tested HNSW/IVFFlat halfvec indexes reduced isolated latency below 0.7 ms
but recall@10 to roughly 94–96%. Production therefore remains exact pgvector
search; ANN is a future benchmark-gated optimization, not a default. The
reproducible benchmark and raw aggregate result live in
`docs/VECTOR_INDEX_BENCHMARK.md` and `docs/benchmarks/vector-index-2026-10-05.json`.

Embedding identity migration is staged: a new provider/model/dimension is fully
written and coverage-checked before the collection contract and active revision
switch atomically. Normal search remains bound to the active contract.

Gate passed: production search uses the VectorIndex-backed PostgreSQL path and no
production search path depends on JsonVectorStore.

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

## DP-SDK-001 — versioned consumer contract and SDKs

Status: COMPLETE.

- [x] publish versioned HTTP consumer contract via /v1/contract;
- [x] lightweight Python SDK without server/runtime dependencies;
- [x] zero-dependency JavaScript ESM SDK;
- [x] Python/JavaScript conformance parity for collection, processing, ingest, search, discovery, entity and relation operations;
- [x] collection_exists / collectionExists and process_document / processDocument parity;
- [x] neutral SearchProfile / search_with_profile / searchWithProfile primitives;
- [x] neutral build_collection_id / buildCollectionId namespace composition;
- [x] consumer-scoped authentication support for protected/federated search;
- [x] release consumer SDK 0.3.0 while keeping HTTP consumer contract 1.x backward-compatible.

Domain-specific ranking weights, collection namespaces and policy remain in each consumer repository.

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

Status: COMPLETE.

Initial production integration merged in Tender Agent PR #144 (cbd5275). Migration closure merged through PRs #151–157, culminating in #157 (9cceb49d).

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
- [x] remove duplicate legacy JSON-vector/generic retrieval code after production acceptance;
- [x] delegate generic document processing/extraction to Data Platform;
- [x] replace Tender Agent-local generic HTTP client surface with the shared Data Platform consumer SDK;
- [x] move procurement retrieval weights and collection namespaces into Tender Agent-owned presets while using neutral SDK primitives.

Code gate passed: existing Tender Agent workflows and CI remain green, and normal retrieval is scoped to one deterministic versioned collection per tender.

Production runtime gate passed on the Mac mini on 2026-10-04. Data Platform is supervised by launchd on 127.0.0.1:8094, uses the dedicated arvectum_data database in the existing pgvector PostgreSQL runtime, and uses the local Qwen3-Embedding-4B embedding service on 127.0.0.1:8090. Pilot tender 0187200001726001304 was indexed as 60 resources / 60 documents / 60 chunks / 60 embeddings. Tender readiness became ready_for_analysis=true; a live hybrid query returned 5 mapped Tender hits in about 0.32 s, and retrieval-only analyze_tender fast mode completed 10 sections with 16 unique sources in about 1.5 s with no warnings or errors.

Legacy parity was rebuilt safely in an isolated temporary JSON-vector index from the same 60 current production chunks using the same Qwen3-Embedding-4B provider, without writing legacy embedding metadata back to production. Across five representative procurement queries, equal-weight Data Platform hybrid retrieval matched legacy semantic top-1 on 4/5 queries and averaged about 0.129 s versus about 0.196 s for legacy retrieval. The one mismatch was traced to a weak singleton PostgreSQL FTS hit over-promoted by equal-weight RRF. Data Platform therefore added generic per-request RRF weights while keeping its platform default at 1:1. Tender Agent PR #146 (4df33d7) selected a semantic-first profile lexical_weight=1, vector_weight=4. Production re-validation then matched the isolated legacy semantic top-1 on 5/5 queries, with Data Platform averaging about 0.159 s for the five-query run. Retrieval-only fast analysis still completed 10 sections with 16 unique sources in about 1.44 s with no warnings or errors.
Migration closure completed on 2026-10-05. Tender Agent PR #151 isolated the legacy RAG path, #152 made Data Platform the default backend, #153 removed the legacy generic RAG backend, #154 removed the local generic document extractor in favor of Data Platform processing, #155 switched consumer calls to the shared SDK, #156 bumped the SDK dependency to 0.2.0, and #157 adopted SDK 0.3.0 consumer-owned search profiles and canonical collection naming. Tender Agent main at 9cceb49d passed CI after the final merge. Data Platform main at 51147af6 also passed its post-merge workflows for consumer SDK 0.3.0.


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

Rechecked on 2026-10-05 against the production Arvectum OS database:
`knowledge_asset_sets`, `knowledge_asset_records`, `postmortem_sets`,
`postmortem_records`, `postmortem_findings`, `archive_export_sets`,
`dashboard_snapshot_sets` and `deal_closure_sets` all still contain zero rows.
The remaining acceptance gate is therefore blocked by the absence of a real
completed upstream deal/postmortem lifecycle, not by Data Platform integration.
Synthetic data is not used to close this real-data gate.

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

## Immediate next priorities

- [x] DP-VEC-001: formalize the VectorIndex protocol boundary.
- [x] DP-VEC-001: benchmark HNSW versus IVFFlat and keep exact pgvector search until ANN passes the relevance gate.
- [x] DP-VEC-001: add explicit model/dimension migration safety for vector indexes.
- [ ] DP-INT-002: close real-data production acceptance on the first non-empty KnowledgeAssetRecord set.
- [ ] DP-BENCH-002: build the competitive frozen-corpus benchmark suite before promoting BM25, learned reranking, bounded LLM reranking, VLM escalation or query expansion. Accepted real-consumer retrieval coverage is now expanded to production_acceptance_v3 (20/20 top-1); multi-format, OCR/layout, adversarial and competitive-reference dimensions remain open.

## AI/model architecture and capability roadmap

Core principle: Data Platform remains deterministic and useful without a generative LLM. Model-backed capabilities are optional providers with explicit contracts, health checks, model identity, timeouts and fail-closed behavior. Consumers decide which capabilities they need.

### Current production model path

- [x] Hybrid retrieval uses a local embedding provider in production.
- [x] Mac mini production uses `Qwen3-Embedding-4B` through the local `llama.cpp` OpenAI-compatible embeddings endpoint on `127.0.0.1:8090/v1`.
- [x] Embeddings are used for semantic/vector retrieval; PostgreSQL FTS provides the lexical side.
- [x] Normal document extraction is deterministic and does not call an LLM or VLM.
- [x] The platform can run lexical-only search without embeddings; production hybrid/vector search requires an embedding provider.
- [x] No generative LLM, "thinking" model or VLM is a hard dependency of the current platform core.

### Model architecture invariants

- [x] Embedding, reasoning/generation and vision are separate roles; one large model is never required to serve every role.
- [x] The deterministic core remains usable without a reasoning LLM or VLM.
- [x] Local-first is the default deployment policy for model-backed capabilities.
- [x] Remote model use must be explicitly enabled; there is no silent fallback from local/private processing to a cloud provider.
- [x] Evidence retrieval happens before synthesis: reasoning models consume bounded, provenance-bearing context rather than becoming an alternative source of truth.
- [x] Model-produced facts/relations are suggestions until validated by deterministic checks, source evidence or explicit review.
- [x] Optional model failure must degrade to a lower capability tier where safe instead of taking down indexing/search.

Target role topology:

~~~text
Data Platform
    |
    +-- EmbeddingProvider  -> semantic indexing/search
    |
    +-- ReasoningProvider  -> bounded rerank / extraction / research / synthesis
    |
    +-- OCRProvider        -> image-to-text for scans
    |
    +-- VisionProvider     -> hard layout / tables / forms / diagrams
~~~

These roles may point to separate local endpoints/models and may be upgraded independently. A "thinking model" is therefore an optional ReasoningProvider, not a platform prerequisite.

### DP-MODES-001 — capability / effort modes

Status: PLANNED.

Expose a product-neutral execution-depth abstraction so consumers can request an outcome level without hard-coding model/provider details.

- [ ] FAST: deterministic lexical + vector hybrid retrieval, no generative LLM required;
- [ ] STANDARD: hybrid retrieval plus bounded reranking when enabled;
- [ ] DEEP: bounded query expansion + multi-pass retrieval + reranking + optional reasoning;
- [ ] RESEARCH: discovery + acquisition + iterative retrieval + contradiction checks + evidence-grounded synthesis;
- [ ] define latency/cost/resource budgets for every mode;
- [ ] make every mode degrade safely when optional model roles are unavailable;
- [ ] expose executed stages, providers and timings in diagnostics without leaking sensitive content;
- [ ] allow consumers to override individual stages only within platform safety/resource bounds.

The mode name describes pipeline depth, not a specific model. Consumers therefore remain portable across local and remote provider choices.

### DP-MODEL-001 — optional local/remote model provider layer

Status: PLANNED.

- [ ] define a product-neutral text-generation/reasoning provider contract;
- [ ] define a product-neutral vision/VLM provider contract;
- [ ] support OpenAI-compatible local endpoints so llama.cpp / compatible local runtimes can be attached without consumer-specific code;
- [ ] keep provider/model/version identity in diagnostics and derived artifacts;
- [ ] add bounded timeouts, retries, health probes and concurrency controls;
- [ ] allow local-first operation with optional remote providers selected explicitly by deployment policy;
- [ ] add per-role routing policy: local-only / explicit remote allowlist / disabled;
- [ ] prohibit implicit cloud fallback when a local provider is unavailable;
- [ ] expose provider capability discovery and readiness per role;
- [ ] record bounded latency/usage/error metrics per provider without logging sensitive prompts/documents;
- [ ] support independent model upgrades/configuration for embedding, reasoning and vision roles;
- [ ] keep search/indexing available when optional generation/VLM providers are unavailable.

The intended deployment separates model roles: embeddings, reasoning/generation and vision may run as different models/endpoints and can be upgraded independently.

### DP-OCR-001 — OCR and multimodal document ingestion

Status: PLANNED.

Extraction cascade:

1. native deterministic parser first;
2. conventional OCR for image-only pages/scans;
3. optional VLM fallback for hard layout, tables, forms, diagrams or low-confidence OCR.

- [ ] detect image-only / low-text PDF pages;
- [ ] add OCR provider protocol and local implementation;
- [ ] preserve page coordinates, confidence and source provenance where available;
- [ ] add optional VLM document-understanding fallback;
- [ ] extract tables/forms without silently flattening structure;
- [ ] benchmark accuracy/latency on real procurement and business documents;
- [ ] never send documents to a remote vision provider unless deployment policy explicitly permits it.

A VLM is therefore not required for ordinary OCR. It is an escalation path for documents where classical OCR/layout extraction is insufficient.

### DP-RERANK-001 — optional intelligent reranking

Status: PLANNED.

- [ ] rerank a bounded top-N candidate set after lexical/vector retrieval;
- [ ] support lightweight cross-encoder and optional reasoning/LLM rerank providers;
- [ ] preserve original lexical/vector/fusion scores for explainability;
- [ ] enable only when frozen relevance benchmarks show a repeatable gain;
- [ ] keep deterministic hybrid retrieval as fallback.

### DP-QE-001 — query expansion

Status: PLANNED.

- [ ] generate bounded synonyms/paraphrases/domain variants;
- [ ] support deterministic dictionaries plus optional model-generated variants;
- [ ] expose every expansion in search diagnostics;
- [ ] benchmark expansion against unexpanded retrieval before enabling by default.

### DP-STRUCT-001 — schema-driven structured extraction service

Status: PLANNED.

- [ ] accept a consumer-supplied extraction schema;
- [ ] extract typed records/fields from documents and web resources;
- [ ] attach evidence/provenance to every extracted field;
- [ ] support deterministic extractors first and optional LLM/VLM extractors where justified;
- [ ] expose confidence/review state instead of pretending uncertain fields are facts.

Example target: extract INN, dates, prices, manufacturer and contract number from a corpus while retaining exact evidence for each field.

### DP-RESEARCH-001 — reusable research workflow

Status: PLANNED.

- [ ] discovery -> fetch -> ingest -> search -> evidence synthesis workflow;
- [ ] bounded source expansion and deduplication;
- [ ] source-quality and contradiction handling;
- [ ] optional reasoning model for synthesis while keeping citations grounded in platform evidence;
- [ ] reusable by Growth, Tender research and future research agents.

### DP-ANSWER-001 — evidence-grounded answer synthesis

Status: PLANNED.

Purpose: turn retrieved evidence into a concise answer without weakening the platform's source-of-truth boundary.

- [ ] accept a bounded set of SearchHit/evidence objects as the only synthesis context by default;
- [ ] support an optional local ReasoningProvider for answer generation;
- [ ] require claim-level source references for material factual statements;
- [ ] surface contradictions instead of silently choosing one source;
- [ ] abstain or mark uncertainty when evidence is insufficient;
- [ ] preserve the underlying retrieval scores, collection IDs and evidence identities;
- [ ] keep synthesis optional so consumers can retrieve raw evidence without invoking any LLM;
- [ ] benchmark answer faithfulness separately from retrieval relevance.

Target pipeline:

~~~text
discovery/acquisition
        ↓
native parser
        ↓ if needed
      OCR
        ↓ if needed
      VLM
        ↓
chunks + structured records
        ↓
PostgreSQL FTS + embeddings
        ↓
hybrid retrieval
        ↓ optional
reranker / query expansion
        ↓ optional
reasoning synthesis
        ↓
answer + evidence + uncertainty
~~~

### DP-GRAPH-002 — evidence-backed knowledge graph enrichment

Status: PLANNED.

- [ ] suggest entity aliases and relations from indexed evidence;
- [ ] keep ambiguity-safe resolution;
- [ ] require explicit policy/review before model-suggested relations become canonical;
- [ ] support temporal relation metadata;
- [ ] expose graph traversal to authorized consumers.

The platform must not silently convert model guesses into canonical graph facts.

### DP-SYNC-001 — continuous indexing

Status: PLANNED.

- [ ] scheduled source refresh;
- [ ] ETag / Last-Modified / content-hash change detection where available;
- [ ] re-fetch/re-index only changed resources;
- [ ] stale/deleted source handling;
- [ ] per-source refresh policy and observability.

### DP-CRAWL-002 — distributed crawling

Status: FUTURE.

- [ ] durable crawl queue;
- [ ] multiple workers with host-level rate limits;
- [ ] deduplication and leases;
- [ ] resumable crawl jobs;
- [ ] only introduce when single-node throughput becomes a measured bottleneck.

### DP-MEM-001 — shared evidence-backed agent memory

Status: PLANNED.

- [ ] let authorized agents persist durable observations/artifacts into scoped collections;
- [ ] distinguish source evidence, agent-derived observation and user-authored memory;
- [ ] retain provenance and producer/model identity;
- [ ] support retrieval across authorized agents without global-data fallback;
- [ ] define retention/deletion and conflict rules before enabling autonomous writes.

### DP-PRODUCT-001 — Data Platform as an external Arvectum product

Status: FUTURE.

Potential product contour: connect documents, websites and APIs -> continuously index them -> expose evidence-backed search/API/SDK for customer AI agents.

Before externalization:
- [ ] tenant isolation and quotas;
- [ ] customer-managed connectors/credentials;
- [ ] billing/usage metering;
- [ ] external auth and key lifecycle;
- [ ] retention/deletion/export controls;
- [ ] deployment/privacy modes including a local/private mode in which documents and model requests never leave customer-controlled infrastructure;
- [ ] explicit per-capability policy for whether remote LLM/VLM providers are permitted;
- [ ] operational SLOs and supportability.

## DP-BENCH-002 — competitive benchmark suite

Status: PLANNED.

Purpose: evaluate Data Platform against mature reference products by layer, using the same frozen corpora and acceptance questions wherever practical. Product adoption decisions remain benchmark-driven rather than feature-checklist-driven.

Reference set:

- RAGFlow — end-to-end RAG/document-understanding reference;
- Unstructured — ingestion/OCR/layout/table extraction reference;
- Qdrant — vector/hybrid retrieval reference;
- Vectara — retrieval/reranking/grounded-answer reference;
- Onyx — connector sync/permissions reference;
- Weaviate — hybrid-search/API ergonomics reference;
- Haystack and LlamaIndex — component/pipeline architecture references;
- Dify and AnythingLLM — end-user knowledge/agent UX references;
- Langfuse — tracing/evaluation/experiment-management reference.

Benchmark corpus strategy:

- [ ] build a frozen corpus from real procurement, business, website and product-research materials;
- [ ] include native PDFs, scanned PDFs, DOCX, XLSX, HTML, malformed/legacy files and mixed Russian/English content;
- [ ] maintain gold answers, relevant-document/chunk judgments and source/evidence identities;
- [ ] version benchmark data and acceptance thresholds;
- [ ] separate public/shareable fixtures from private production-derived fixtures;
- [ ] add adversarial cases for collection isolation, stale sources, duplicate content and conflicting evidence.

Required benchmark dimensions:

- [ ] ingestion success rate by format;
- [ ] OCR word/character accuracy on scanned material;
- [ ] table/form structure preservation;
- [ ] fact-preserving chunking quality;
- [ ] exact identifier/number/date/amount retrieval;
- [ ] semantic retrieval quality using Recall@k, MRR and nDCG;
- [ ] Russian-language retrieval quality;
- [ ] reranking uplift over base hybrid retrieval;
- [ ] citation correctness and citation completeness;
- [ ] evidence entailment / groundedness of generated claims;
- [ ] abstention quality when evidence is insufficient;
- [ ] contradiction surfacing across sources;
- [ ] multi-hop evidence retrieval;
- [ ] zero cross-collection / cross-tenant leakage;
- [ ] incremental-sync efficiency: changed resources versus total reprocessed resources;
- [ ] latency p50/p95/max by pipeline stage;
- [ ] CPU/RAM/GPU footprint and throughput;
- [ ] fully local/private execution coverage.

Competitive acceptance rule: no external system needs to be beaten on every dimension. Data Platform must meet its own product gates and document where a reference product is materially better, so the gap can be either intentionally accepted or added to the roadmap.

### Benchmark-driven adoption gates

- [ ] BM25 backend only if frozen corpora show a repeatable lexical-quality gap over PostgreSQL FTS;
- [ ] ANN indexes only if latency/throughput gain justifies measured recall loss at production scale;
- [ ] learned/cross-encoder reranker only if it improves nDCG/MRR enough to justify added latency/resources;
- [ ] LLM reranking only if it beats lighter reranking on accepted relevance/cost gates;
- [ ] VLM escalation only where OCR/layout benchmarks justify it;
- [ ] query expansion only if recall improves without unacceptable precision/latency regression;
- [ ] answer synthesis only if groundedness/citation benchmarks meet the required threshold.

## Post-v1 backlog

Only after three real consumers are integrated:

- [x] entity resolution;
- [x] entity graph/relations;
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

Production acceptance v3 expands the frozen accepted suite to 20 real cases:
all v2 cases plus six stable real Search Console/Webmaster intents and four live
document-routing cases from procurement 0137200001226007700. The first
production run on 2026-10-05 passed 20/20 at top-1 with MRR=1.0,
hit-rate@5=1.0 and mean recall@5=1.0; latency was about 95.8 ms p50,
127.4 ms p95 and 184.0 ms max. Known non-top-1 Search Console intents remain
in the diagnostic suite instead of being relabeled to make acceptance pass.
This larger accepted baseline still does not justify enabling deferred BM25,
learned/LLM reranking or platform-generated query expansion without a measured
incremental gain.

Entity resolution is now deterministic and ambiguity-safe: exact normalized aliases return resolved, ambiguous, or unresolved; the platform never auto-merges multiple candidates. Canonical names are stored as name aliases, while stable identifiers can use separate alias kinds.

Entity relations are now explicit, directed and provenance-aware. A relation links two existing entities with a relation type and may reference a validated collection/resource/document/chunk chain. Relation IDs are deterministic, repeated writes are idempotent, self-links are rejected, and the platform does not infer graph edges automatically from text.

The first production consumer is Arvectum Site. Its product-entity sync resolves Arvectum by domain and published products by canonical URL, then writes deterministic publishes relations backed by exact product-search evidence. Initial production acceptance created 2 entities, 6 aliases and 1 relation; an immediate second run reused the same entity and relation IDs with no duplicates.

Entity graph relations are now explicit, evidence-aware and idempotent: relation IDs are deterministic over source/target/type plus evidence identity; inbound/outbound traversal is supported; provenance mismatches fail closed; the platform does not infer relations automatically.

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
DP-SDK-001
    ↓
DP-INT-001 Tender Agent
    ↓
DP-INT-002 Arvectum OS
    ↓
DP-INT-003 Growth/SEO
    ↓
DP-OPS-001
    ↓
DP-BENCH-002
    ↓
DP-MODES-001 + DP-MODEL-001
    ↓
DP-OCR-001 + DP-RERANK-001 + DP-QE-001
    ↓
DP-STRUCT-001 + DP-ANSWER-001
    ↓
DP-RESEARCH-001 + DP-SYNC-001 + DP-MEM-001
~~~

The first code task is deliberately not “write a new search engine”. It is to promote the mature extraction foundation into its canonical repository, then build the missing search layers around real consumer requirements.
