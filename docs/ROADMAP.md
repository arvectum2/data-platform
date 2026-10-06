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

Status: COMPLETE (2026-10-05).

- [x] define a product-neutral text-generation/reasoning provider contract;
- [x] define a product-neutral vision/VLM provider contract;
- [x] support OpenAI-compatible local endpoints so llama.cpp / compatible local runtimes can be attached without consumer-specific code;
- [x] keep provider/model/version identity in diagnostics and model responses so derived artifacts can preserve provenance;
- [x] add bounded timeouts, retries, health probes and concurrency controls;
- [x] allow local-first operation with optional remote providers selected explicitly by deployment policy;
- [x] add per-role routing policy: local-only / explicit remote allowlist / disabled;
- [x] prohibit implicit cloud fallback when a local provider is unavailable;
- [x] expose provider capability discovery and readiness per role via `/v1/status` and `/v1/models/status?probe=true`;
- [x] record bounded latency/usage/error metrics per provider without logging sensitive prompts/documents;
- [x] support independent model upgrades/configuration for embedding, reasoning and vision roles;
- [x] keep search/indexing available when optional generation/VLM providers are unavailable.

Implementation notes: `docs/MODEL_PROVIDERS.md`. `local-only` is enforced with a loopback endpoint check; retries never change endpoint/provider.

The intended deployment separates model roles: embeddings, reasoning/generation and vision may run as different models/endpoints and can be upgraded independently.

### DP-OCR-001 — OCR and multimodal document ingestion

Status: IN PROGRESS (2026-10-05).

Extraction cascade:

1. native deterministic parser first;
2. conventional OCR for image-only pages/scans;
3. optional VLM fallback for hard layout, tables, forms, diagrams or low-confidence OCR.

- [x] detect image-only / low-text PDF pages;
- [x] add OCR provider protocol and local Tesseract implementation;
- [x] preserve page coordinates, confidence and source provenance where available;
- [x] add optional VLM document-understanding fallback for low-text / low-confidence OCR pages;
- [x] preserve tables/forms in the VLM contract instead of silently requesting flat prose;
- [ ] benchmark accuracy/latency on a larger frozen set of real procurement and business documents;
- [x] never send documents to a remote vision provider unless deployment policy explicitly permits it.

Real acceptance (2026-10-05): a scanned PDF from the existing Tender Agent procurement corpus had 0 native extracted characters; the local OCR cascade selected its single page and recovered 925 characters at 93.16% mean Tesseract confidence without VLM escalation. Implementation: `docs/OCR_MULTIMODAL.md`.

A VLM is therefore not required for ordinary OCR. It is an escalation path for documents where classical OCR/layout extraction is insufficient.

### DP-RERANK-001 — optional intelligent reranking

Status: COMPLETE (2026-10-05); default activation remains benchmark-gated.

- [x] rerank a bounded top-N candidate set after lexical/vector retrieval;
- [x] add a provider-neutral reranker protocol and reasoning/LLM implementation;
- [x] preserve original lexical/vector/fusion scores plus a separate rerank score for explainability;
- [x] add a frozen-benchmark quality/latency gate; reranking remains opt-in until a repeatable gain is demonstrated;
- [x] keep deterministic hybrid retrieval as fail-open fallback when disabled, unavailable or invalid.

Implementation notes: `docs/RERANKING.md`. The existing production acceptance v3 suite is already 20/20 top-1 with MRR 1.0, so it cannot prove positive rerank gain; default activation correctly remains off pending a harder frozen relevance suite.

### DP-QE-001 — query expansion

Status: COMPLETE (2026-10-05); default activation remains benchmark-gated.

- [x] generate bounded synonyms/paraphrases/domain variants;
- [x] support deterministic dictionaries plus optional policy-controlled model-generated variants;
- [x] expose every automatic expansion, source and weight in search diagnostics;
- [x] add an unexpanded-vs-expanded frozen benchmark gate before any default activation.

Implementation: `docs/QUERY_EXPANSION.md`. Production acceptance v3 is already perfect on top-1, MRR and recall@5, so automatic expansion correctly remains opt-in until a harder frozen suite demonstrates measurable gain.

### DP-STRUCT-001 — schema-driven structured extraction service

Status: COMPLETE (2026-10-05).

- [x] accept a consumer-supplied extraction schema;
- [x] extract typed fields from text/documents and governed web resources;
- [x] attach evidence/provenance to every selected value and candidate;
- [x] support deterministic extraction first and explicit policy-controlled reasoning/LLM extraction;
- [x] expose confidence, candidates and review/unresolved state instead of pretending uncertain fields are facts.

Implementation: `docs/STRUCTURED_EXTRACTION.md`. The existing generic extraction engine, record boundaries and Postgres record/provenance primitives are reused rather than duplicated. Model candidates require a verbatim source excerpt that is verified before resolution.

Example target: extract INN, dates, prices, manufacturer and contract number from a corpus while retaining exact evidence for each field.

### DP-RESEARCH-001 — reusable research workflow

Status: COMPLETE (2026-10-05).

- [x] discovery -> governed fetch/ingest -> indexing -> search -> evidence synthesis workflow;
- [x] bounded source expansion and canonical-URI deduplication;
- [x] per-source acquisition status/warnings plus contradiction handling through DP-ANSWER;
- [x] optional reasoning model for synthesis while keeping citations grounded in platform evidence;
- [x] reusable consumer-neutral API for Growth, Tender research and future research agents.

Implementation: `docs/RESEARCH_WORKFLOW.md`. Discovery, acquisition, parsing, retrieval and synthesis remain separate reusable platform boundaries; the research layer only orchestrates them.

### DP-ANSWER-001 — evidence-grounded answer synthesis

Status: COMPLETE (2026-10-05); production activation remains faithfulness-gated.

Purpose: turn retrieved evidence into a concise answer without weakening the platform's source-of-truth boundary.

- [x] accept a bounded set of SearchHit/evidence objects as the only synthesis context by default;
- [x] support an optional policy-controlled ReasoningProvider for answer generation;
- [x] require claim-level chunk references for material factual statements and reject unknown citations;
- [x] surface contradictions instead of silently choosing one source;
- [x] abstain or mark uncertainty when evidence is insufficient or synthesis fails validation;
- [x] preserve underlying retrieval scores, collection metadata and evidence identities;
- [x] keep synthesis optional so consumers can retrieve raw evidence without invoking any LLM;
- [x] define answer-faithfulness evaluation separately from retrieval relevance.

Implementation: `docs/ANSWER_SYNTHESIS.md`. Production rollout remains gated on a frozen faithfulness suite covering claim support, contradiction recall, abstention correctness and synthesis latency.

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

Status: COMPLETE (2026-10-05).

- [x] suggest entity aliases and relations from bounded indexed evidence;
- [x] keep existing ambiguity-safe entity resolution;
- [x] require explicit review before proposed/model-suggested relations become canonical;
- [x] support temporal relation metadata with validated intervals;
- [x] expose bounded canonical graph traversal to authorized API consumers.

Implementation: `docs/KNOWLEDGE_GRAPH.md`. Model output is suggestion-only, proposed relations require chunk evidence, and proposed/rejected edges never enter canonical traversal. The platform does not silently convert model guesses into graph facts.

### DP-SYNC-001 — continuous indexing

Status: COMPLETE (2026-10-05).

- [x] scheduled/due source refresh boundary with per-resource next-run state;
- [x] ETag / Last-Modified capture plus authoritative content-hash change detection;
- [x] re-fetch/re-index only changed resources; unchanged content skips embedding;
- [x] stale source handling without deleting last-known evidence;
- [x] per-source refresh policy and durable refresh-run observability.

Implementation: `docs/CONTINUOUS_INDEXING.md`. Scheduling is intentionally external to the API process; cron/systemd/Arvectum orchestration invokes the bounded due-work endpoint.

### DP-CRAWL-002 — distributed crawling

Status: FUTURE.

- [ ] durable crawl queue;
- [ ] multiple workers with host-level rate limits;
- [ ] deduplication and leases;
- [ ] resumable crawl jobs;
- [ ] only introduce when single-node throughput becomes a measured bottleneck.

### DP-MEM-001 — shared evidence-backed agent memory

Status: COMPLETE (2026-10-05).

- [x] authorized agents can persist durable observations into explicitly write-enabled scoped collections;
- [x] distinguish source evidence, agent-derived observation and user-authored memory;
- [x] retain source-chunk provenance plus authenticated producer and declared model identity;
- [x] retrieval across authorized agents uses normal collection-scoped search with no global-data fallback;
- [x] explicit retention/deletion boundary and append/supersede/reject conflict rules are defined before autonomous writes.

Implementation: `docs/AGENT_MEMORY.md`. Writes are deny-by-default through `memory_writers`; source evidence must be an exact indexed excerpt, agent observations require source chunks, and user memory has a separate writer policy.

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

Status: IN PROGRESS (2026-10-06).

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
- [x] version benchmark data and acceptance thresholds;
- [x] separate public/shareable fixtures from private production-derived fixtures;
- [ ] add adversarial cases for collection isolation, stale sources, duplicate content and conflicting evidence.

Required benchmark dimensions:

- [x] ingestion success rate by format;
- [x] OCR word/character accuracy on scanned material;
- [x] table/form structure preservation;
- [x] fact-preserving chunking quality;
- [x] exact identifier/number/date/amount retrieval;
- [x] semantic retrieval quality using Recall@k, MRR and nDCG;
- [x] Russian-language retrieval quality;
- [x] reranking uplift over base hybrid retrieval;
- [x] citation correctness and citation completeness;
- [x] evidence entailment / groundedness of generated claims;
- [x] abstention quality when evidence is insufficient;
- [x] contradiction surfacing across sources;
- [ ] multi-hop evidence retrieval;
- [x] zero cross-collection / cross-tenant leakage;
- [x] incremental-sync efficiency: changed resources versus total reprocessed resources;
- [ ] latency p50/p95/max by pipeline stage;
- [ ] CPU/RAM/GPU footprint and throughput;
- [ ] fully local/private execution coverage.

Competitive acceptance rule: no external system needs to be beaten on every dimension. Data Platform must meet its own product gates and document where a reference product is materially better, so the gap can be either intentionally accepted or added to the roadmap.

Foundation increment (2026-10-06): benchmark suites are now registered in benchmarks/catalog_v1.json with frozen SHA-256 digests, case counts, visibility classification, covered dimensions and thresholds. The validator fails closed on silent suite mutation. Reusable CER/WER, nDCG@k and evidence-set precision/recall metrics were added for the OCR/retrieval/citation benchmark layers. See docs/COMPETITIVE_BENCHMARKS.md. Multi-format gold fixtures, adversarial cases and external reference adapters remain open.

Corpus increment (2026-10-06): benchmarks/corpora/public_v1 now pins real public procurement and Arvectum website fixtures across native PDF, DOCX, XLSX and HTML, plus two image-only scans derived from real procurement pages. The executable corpus runner reports extraction success by format, latency and OCR CER/WER against pinned reference text. Live local Tesseract acceptance passed 7/7 artifacts: the linear scan measured CER 3.61% / WER 5.86% at 94.41% confidence, while the table/form layout-stress scan measured CER 35.78% / WER 74.47% at 86.89% confidence. Separate per-case regression ceilings prevent aggregate averages from hiding one degraded OCR profile. Product-research material, malformed/legacy inputs, mixed-language coverage and human-reviewed OCR gold remain open. Native DOCX/XLSX row-cell preservation and PDF form label/value preservation are now scored independently from text accuracy; the OCR layout-stress profile keeps structure and reading-order quality as separate signals.

Adversarial increment (2026-10-06): benchmarks/adversarial_v1.json now executes five invariants against the real PostgreSQL platform path: collection isolation, consumer/tenant fail-closed isolation, federated duplicate canonical-URI suppression, preservation of distinct conflicting evidence, and stale-source last-known-evidence retention. Isolated Mac mini PostgreSQL acceptance passed 5/5: zero forbidden collection hits, unauthorized consumer denied, duplicate canonical URI collapsed to one winner, both conflicting evidence sources preserved, and refresh_error -> stale retained the original content hash plus searchable last-known evidence. The required pass rate is 1.0; contradiction detection itself remains a separate benchmark dimension rather than being inferred from source preservation alone.

Exact-fact increment (2026-10-06): benchmarks/fact_preservation_v1.json binds six real PDF/DOCX/XLSX facts to their expected source and local context. Default chunking preserved every exact fact together with its context (6/6), and isolated PostgreSQL lexical acceptance returned the expected document top-1 for all six exact queries. Coverage includes an identifier, dates, an OKPD2/classification number and monetary amounts; both chunk/context preservation and retrieval top-1 gates are fixed at 1.0.

Semantic retrieval increment (2026-10-06): nDCG now deduplicates repeated result identities before scoring, preventing multiple chunks from the same canonical URI from creating impossible relevance gain above 1.0. Re-run of production_acceptance_v3 scored top-1=1.0, MRR=1.0, recall@5=1.0 and mean nDCG@5=0.9953 against a fixed 0.99 gate. The remaining growth-photo-pixels ordering gap stays visible as benchmark debt instead of being relabeled or hidden.

Russian retrieval increment (2026-10-06): russian_retrieval_v1 freezes the 19 production-accepted cases with Cyrillic queries from production_acceptance_v3. Live production acceptance passed top-1=1.0, MRR=1.0, recall@5=1.0 and mean nDCG@5=0.9951 against the same 0.99 gate, with about 114 ms p50 / 142 ms p95 latency. Russian quality is therefore measured independently from the mixed-language aggregate.

Faithfulness increment (2026-10-06): faithfulness_v1 adds four frozen local-model cases covering supported exact facts, insufficient-evidence abstention, conflicting deadlines and a two-source contract-to-supplier inference. Gemma 4 12B passed the unchanged 1.0 gates for citation precision/recall, exact cited-evidence support, abstention accuracy, contradiction recall and required answer terms. Mean synthesis latency was about 7.4 s and max about 9.8 s. This closes the first deterministic faithfulness dimensions while a larger real-source suite remains future benchmark work.

Rerank comparison increment (2026-10-06): growth_search_console_v1 provides an unsaturated real-intent baseline (top-1 0.50 / MRR 0.5833 / mean nDCG@5 0.6468, ~251 ms p95 on the measured run). The local Gemma reranker, even bounded to five candidates, exceeded a 5 s request timeout versus an accepted <=3x baseline ceiling of ~752 ms. The reranking benchmark dimension is therefore measured, but the current LLM implementation fails promotion and remains explicit opt-in. A lighter learned/cross-encoder candidate remains a future adoption experiment.

Incremental-sync increment (2026-10-06): sync_efficiency_v1 exercises no-change, single-change and all-change refresh cycles over three URL resources on an isolated PostgreSQL database. Acceptance passed 3/3: unchanged resources caused zero index/embedding work, one changed resource caused exactly one index plus one embedding write, and three changes caused exactly three. Aggregate indexing amplification is 1.0 with zero unnecessary indexed resources.

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
