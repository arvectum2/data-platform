# Arvectum Data Platform

Shared data acquisition, extraction, indexing and search foundation for Arvectum products.

## Why this repository exists

Several Arvectum products need the same primitives:

- Tender Agent — procurement discovery, document ingestion, RAG and evidence-backed retrieval;
- Arvectum OS — internal knowledge/RAG search;
- Growth / SEO automation — web discovery, crawling, indexing and research;
- future parsers and research agents — reusable acquisition and structured extraction.

This repository becomes the canonical source of truth for reusable capabilities. Product-specific business logic remains in product repositories.

## Current status

Foundation implementation is active. The repository is now an installable Python package/service and contains the promoted product-neutral acquisition/extraction engine from Discount Parser.

Verified locally on Python 3.11: the platform suite is green, the promoted Discount Parser engine remains compatible, document ingestion and embedding primitives are platform-owned, and PostgreSQL FTS + pgvector hybrid retrieval has passed live isolated-database acceptance.

Audit baseline:

- data-platform: 3701dda38c36
- discount-parser: 4bde0909d18b
- tender-agent: 3bbca3dc615b

Migration is incremental: no big-bang rewrite and no product outage while ownership moves here.

## Target v1

~~~text
sources / URLs / APIs / files
            |
        discovery
            |
        acquisition
            |
   extraction / parsing
            |
 document + record model
            |
      normalization
            |
    chunking / indexing
        /         \
  lexical       vector
        \         /
        hybrid search
            |
 ranking + filtering
            |
 evidence / provenance
            |
       API + Python SDK
~~~

## Architectural rules

1. data-platform owns reusable infrastructure, not Tender/SEO/Discount business rules.
2. Search is collection-scoped by default; accidental global retrieval is not allowed.
3. Every searchable result preserves source/provenance and evidence.
4. PostgreSQL is the production search datastore; lightweight local stores remain useful for tests/dev.
5. Hybrid retrieval combines lexical and vector candidate sets deterministically before any optional LLM step.
6. Product integrations migrate through compatibility adapters; existing products stay operational throughout extraction.
7. Product-specific connectors can use the connector SDK without being pulled into the platform core.

## Documentation

- [Reuse audit](docs/REUSE_AUDIT.md)
- [Architecture v1](docs/ARCHITECTURE_V1.md)
- [Migration roadmap](docs/ROADMAP.md)
- [ADR-0001: platform boundary and migration strategy](docs/adr/0001-platform-boundary.md)

## Immediate next milestone

DP-API-001: expose collections, ingest and the working hybrid search engine through stable /v1 HTTP contracts, then begin Tender Agent integration behind its current retrieval facade.
