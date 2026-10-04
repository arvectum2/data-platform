# ADR-0001 — Platform boundary and migration strategy

Status: Accepted  
Date: 2026-10-04

## Context

Reusable acquisition, extraction and search functionality currently exists in multiple Arvectum repositories. Tender Agent, Arvectum OS and Growth/SEO automation now need the same foundation.

## Decision

1. arvectum2/data-platform becomes the canonical repository for reusable acquisition, extraction, document processing, indexing and search infrastructure.
2. The Python namespace remains arvectum_data.
3. Existing products remain independent consumers; their business/domain models are not merged into Data Platform.
4. Migration uses compatibility/strangler replacement. Working product paths are replaced only after regression acceptance.
5. Production retrieval uses PostgreSQL lexical search plus pgvector, combined through deterministic hybrid fusion.
6. Search is scoped to explicit collections by default.
7. Provenance/evidence is mandatory in the canonical SearchHit contract.
8. LLM ranking is not part of the mandatory first-stage retrieval path.

## Consequences

Benefits: one foundation for several products, fewer duplicated crawlers/embedders/retrievers, shared relevance evaluation, safer isolation and evidence contracts, incremental migration risk.

Costs: temporary compatibility layers and duplicate code during migration; Data Platform needs its own migrations/CI/service operations; products must distinguish generic relevance from domain ranking.

## Rejected alternatives

### Keep implementations inside each product

Rejected because three independent consumers already need the same foundation and divergence is already visible.

### Merge Tender Agent domain models into Data Platform

Rejected because procurement semantics would make the platform a poor neutral foundation for SEO and Arvectum OS.

### Big-bang move of all search/RAG code

Rejected because current Tender Agent code is coupled to procurement persistence and working product behavior must remain protected.

### LLM-first universal search

Rejected because deterministic lexical/vector retrieval is cheaper, testable, traceable and sufficient as the first-stage foundation.
