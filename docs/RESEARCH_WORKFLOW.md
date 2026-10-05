# Reusable research workflow

DP-RESEARCH-001 composes existing Data Platform boundaries into one bounded workflow:

`discovery -> governed URL ingestion -> indexing -> hybrid retrieval -> grounded answer`

The workflow intentionally does not implement a second crawler, parser, search engine or answer layer.

## Safety and provenance

- Source discovery is connector-controlled and bounded to at most 25 candidates per run.
- Canonical URLs are deduplicated before acquisition.
- Every URL is passed through the existing governed ingestion path, including public-URL/SSRF policy.
- One failed source does not abort the run; it remains visible with an error class and warning.
- Only successfully indexed material can become retrieval evidence.
- Final synthesis uses DP-ANSWER and therefore cannot cite a chunk outside the bounded retrieved evidence set.
- If reasoning is disabled or synthesis fails validation, research returns an explicit abstention while preserving sources and evidence.

## API

`POST /v1/research` accepts a query, target collection, discovery connector, source/evidence bounds, and optional query expansion/reranking. It returns source acquisition status, retrieval evidence, grounded claims, contradictions, uncertainty and warnings.

The workflow is consumer-neutral and can be reused by Tender Agent, Growth research and future agents.
