# Arvectum Data Platform — Architecture v1

Status: accepted initial architecture  
Date: 2026-10-04

## 1. Product boundary

Data Platform is a reusable data acquisition + indexing + retrieval service/library.

It owns acquisition, crawling, generic structured extraction, document text extraction, normalization primitives, chunking, embedding generation, lexical/vector indexing, hybrid retrieval, metadata filters, provenance/evidence, connector contracts, and index lifecycle/operational status.

It does not own procurement bid decisions, procurement law semantics, supplier ranking, SEO strategy, App Store optimization rules, discount publishing, Arvectum OS agent policy, or report-writing business workflows.

## 2. Deployment model

v1 supports two consumption modes over one implementation:

1. Python SDK/package (arvectum_data) for focused reuse, offline workflows and tests.
2. HTTP service for long-lived shared indexes and cross-product access.

~~~text
Tender Agent ───────┐
Arvectum OS ────────┼── HTTP / Python SDK ── Data Platform
Growth / SEO Agent ─┘
~~~

## 3. Logical architecture

~~~text
Connectors (web / API / file / registry)
                  |
              Discovery
                  |
             Acquisition
       HTTP / browser / files
                  |
              Processing
 structured extraction / readable text
 normalization / chunking
                  |
               Storage
 collections / resources / documents
 records / chunks / provenance / runs
             /           \
       Lexical           Vector
   PostgreSQL FTS       pgvector
             \           /
              Hybrid Search
         filters / RRF / ranking
                  |
           evidence-bearing hits
                  |
              API / SDK
~~~

## 4. Package layout

~~~text
src/arvectum_data/
├── core/
├── acquisition/
├── crawl/
├── extraction/
│   ├── fields/
│   ├── records/
│   └── documents/
├── processing/
├── connectors/
├── storage/
├── indexing/
├── search/
├── evidence/
├── execution/
├── review/
├── api/
└── observability/
~~~

During migration existing import paths are preserved. Reorganization happens only after compatibility tests exist.

## 5. Canonical data model

The platform should not force every domain into one giant entity table.

### Collection


### Collection identity

collection_id is the durable identity. Owner and human-readable name are labels, not uniqueness keys. Versioned collections may therefore reuse the same owner/name while changing only their deterministic collection ID/revision. This is required for atomic consumer-side corpus rollover without mutating the previous accepted collection.

Isolation and indexing boundary. Examples:

- tender-agent:procurement-documents
- arvectum-os:knowledge
- growth:arvectum-site
- growth:appstore-competitors

Properties include collection ID, owner/product namespace, access policy, default language, retention policy and active index revision.

### Resource

A discovered/acquired source object: URL, API object, uploaded file or registry item.

Key fields: stable resource ID, collection ID, source/provider, canonical URI, external ID, content hash, first/last seen, metadata and acquisition status.

### Document

Text-bearing projection of a resource: document ID, resource ID, title, normalized text, language, MIME/type, extraction metadata and content hash.

### Record

Structured extraction from a resource/document: record ID, parent, typed fields, field decisions, evidence, revision/review status. The durable multi-record model from arvectum_data is the starting implementation.

### Chunk

Searchable document segment: chunk ID, document ID, ordinal, text, offsets, token estimate, content hash and metadata.

### Evidence / provenance

Every search result must be traceable to source URI/provider/external ID, resource/document/chunk or record ID, text offsets or structured source ref, acquisition/index revision, timestamp and content hash where applicable.

## 5.1 Entity resolution

Entity resolution is a reusable exact-match primitive. Entities have a stable ID, type, canonical name and aliases. Alias normalization uses Unicode NFKC, case-folding and whitespace collapsing only. Aliases are not globally unique, so resolution returns resolved, ambiguous or unresolved. Ambiguous candidates are never auto-merged. Product-specific identity authority rules remain in consumers.

Entity relations are stored only when a consumer explicitly records them. Each relation has source entity, target entity, relation type, optional collection/resource/document/chunk evidence and metadata. Relation IDs are deterministic for the same fact/evidence tuple, making repeated writes idempotent. The platform supports inbound, outbound and bidirectional traversal, but does not infer new edges.

## 6. Search contract

Normal product search requires explicit collections.

Conceptual request:

~~~json
{
  "query": "силовой кабель ВВГнг 4x25",
  "collections": ["tender-agent:procurement-documents"],
  "filters": {"source_type": ["document"]},
  "limit": 20,
  "mode": "hybrid",
  "lexical_weight": 1.0,
  "vector_weight": 1.0
}
~~~

Conceptual SearchHit:

~~~json
{
  "hit_id": "...",
  "resource_id": "...",
  "document_id": "...",
  "chunk_id": "...",
  "record_id": null,
  "title": "...",
  "preview": "...",
  "canonical_uri": "...",
  "scores": {
    "lexical": 0.0,
    "vector": 0.0,
    "fusion": 0.0,
    "rerank": null
  },
  "metadata": {},
  "evidence": [],
  "index_revision": "..."
}
~~~

Scores remain separate; vector cosine, FTS rank and fused rank are not treated as the same scale.

### Federated search authorization

Single-collection search remains backward-compatible for unrestricted collections. Multi-collection search is a federated operation and requires a consumer-scoped identity:

~~~text
X-Arvectum-Consumer: growth-agent
X-Arvectum-Consumer-Key: <consumer-scoped secret>
~~~

Consumer keys are configured through `ARVECTUM_DATA_CONSUMER_API_KEYS` as a JSON object mapping consumer IDs to secrets. They are independent from the general internal API key.

Collections may additionally declare an access policy at create/update time:

~~~json
{
  "access_policy": {
    "allowed_consumers": ["growth-agent"]
  }
}
~~~

If `allowed_consumers` is non-empty, even single-collection search requires a valid consumer-scoped identity and the consumer must be listed. A federated request is authorized only when the consumer key is valid and every requested collection permits that consumer. Search never silently drops unauthorized collections or broadens scope.

For multi-collection search, duplicate hits with the same canonical URI from different collections are collapsed after ranking. The first-ranked collection wins that URI. Multiple chunks from the same winning collection are preserved, because chunk-level retrieval remains part of the search contract. Federation uses bounded overfetch before deduplication so removing mirrored results does not unnecessarily under-fill the requested limit.


## 6.1 Entity resolution and relations

Entity resolution is deliberately conservative. Canonical names and aliases are normalized with Unicode NFKC, case-folding and whitespace collapse. Exact alias lookup returns resolved, ambiguous, or unresolved.

The platform does not automatically merge ambiguous names. Stable identifiers should use a dedicated alias kind such as identifier.

Entity relations are explicit directed edges between existing entities. A relation has a deterministic identity over source entity, target entity, relation type and optional provenance chain. Provenance may reference collection, resource, document and chunk; supplied IDs are validated as one consistent chain before the edge is stored. Repeated identical writes are idempotent.

The platform does not infer relations automatically from free text. Automatic extraction remains a separate future concern and must preserve the same provenance and ambiguity rules.

## 7. Hybrid ranking v1

Deterministic path:

1. lexical candidate retrieval;
2. vector candidate retrieval;
3. metadata/security filtering;
4. reciprocal-rank fusion (RRF);
5. deterministic domain-neutral boosts where evidence exists;
6. optional product-specific ranker hook;
7. optional LLM reranker disabled by default.

RRF is the first fusion strategy because it avoids fragile normalization across incompatible scoring scales and is easy to test.

Hybrid search supports non-negative per-request fusion weights. The platform default is equal-weight RRF (lexical_weight=1, vector_weight=1), so existing consumers keep stable behavior. Products may select a different ranking profile when benchmark evidence justifies it; Tender Agent can prefer semantic retrieval without changing Data Platform defaults for Growth/SEO or Arvectum OS.

### Lexical backend

Production default: PostgreSQL full-text search with language-aware configuration and exact/token metadata signals.

This is not claimed as BM25. If benchmark evidence later justifies true BM25, a dedicated backend can be added behind the LexicalIndex protocol.

### Vector backend

Production default: PostgreSQL + pgvector with an actual vector column and indexed similarity query.

The current Tender Agent JSON vector store remains a local/test backend, not the production engine.

## 8. Security and isolation

The current Tender Agent safety invariant is generalized: normal search never silently falls back from a scoped collection to global data.

Rules:

- collection filtering occurs inside retrieval, not only after ranking;
- connector credentials never enter indexed metadata;
- raw artifacts are retained only under explicit collection policy;
- status/diagnostics are secret-free;
- URLs are validated to prevent SSRF;
- safe file/archive extraction constraints are preserved;
- index rebuilds are revisioned and switch atomically.

## 9. Connector model

Core contract:

~~~text
discover(query, cursor) -> DiscoveredResource[]
fetch(resource)         -> AcquisitionResult
~~~

Core/general connectors: manual URL, generic web search, sitemap/site crawl, file/folder ingest and generic HTTP/API primitives.

Product-specific connectors such as 44-FZ/223-FZ/EIS remain in Tender Agent initially. They consume platform contracts without defining the platform core.

## 10. Storage strategy

Production: PostgreSQL owns canonical searchable metadata, chunks, index revisions and vector data. This reuses an already-operational dependency, provides pgvector + FTS, and avoids adding Elasticsearch/OpenSearch for v1.

Local/test: protocol-compatible in-memory/JSON/SQLite stores remain for deterministic tests and embedded/offline compatibility.

## 11. API v1 surface

~~~text
GET  /health
GET  /v1/status

POST /v1/collections
GET  /v1/collections/{id}

POST /v1/ingest/url
POST /v1/ingest/document
POST /v1/ingest/records

POST /v1/search

POST /v1/index/rebuild
GET  /v1/index/jobs/{id}

POST /v1/extract
~~~

Connector-specific product endpoints do not leak into the core API.

## 12. Compatibility strategy

### Discount Parser

Promote arvectum_data preserving behavior, publish/install it, switch Discount Parser imports to the external package, run engine/product regressions, then remove the duplicate only after acceptance.

### Tender Agent

Add Data Platform interfaces alongside current code and introduce Data Platform Search behind the existing RAG facade. Tender Agent remains the canonical owner of procurement-domain documents/chunks and citation IDs; those chunks are sent through the platform's pre-chunked ingest contract so Data Platform owns indexing/retrieval without re-chunking or absorbing procurement semantics. Run existing RAG/eval suites and remove legacy duplicates only after production acceptance.

### Arvectum OS / Growth

Integrate only after one existing product successfully consumes the platform. This keeps API design grounded in real consumers.

## 13. Non-goals for v1

Do not block v1 on a universal entity graph, autonomous LLM crawling, LLM-first ranking, Elasticsearch/OpenSearch, distributed crawler fleet, internet-scale indexing, moving all domain connectors, or replacing product databases.


## Architectural boundaries

Data Platform is the owner of reusable data/search infrastructure: acquisition, document text extraction, normalization, chunking, embeddings, lexical/vector/hybrid retrieval, generic indexing and reindex lifecycle, reusable Resource / Document / Chunk / Provenance models, deduplication/retries/storage primitives, and generic search/filter/ranking contracts.

Consumer products depend on Data Platform. Data Platform must not import or encode consumer-domain logic. In particular, Tender Agent keeps EIS/44-FZ/223-FZ semantics, procurement requirements, application composition, Decision Core, Commercial Core, GO/NO-GO, supplier/tender compatibility, procurement rules/evidence mapping, and tender reporting. SEO/research agents and Arvectum OS RAG follow the same consumer direction.

The dependency direction is therefore Tender Agent / SEO / Arvectum OS -> Data Platform, never the reverse. The /v1/process/document endpoint exists specifically so consumers can reuse platform-owned extraction and chunking without copying those implementations into their own repositories; consumers may keep domain-local projections of the resulting chunks when their business logic requires stable local references.
