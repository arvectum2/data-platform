# Data Platform: reusable terminology-aware search (v0.1)

Implementation: `src/arvectum_data/search/terminology.py`, generic `SearchQuery`, `/v1/search`, SDK `arvectum_data_client.search`. **No industry-specific vocabulary is hard-coded in Data Platform.**

## Contract

The existing `POST /v1/search` endpoint supports optional terminology fields. The authenticated `GET /v1/contract` advertises capability `terminology_search_v1`; callers should refuse to issue terminology requests to older backends rather than misclassifying unexpanded results.

- `terminology_groups`: 0–12 per-request groups. Each group contains a stable `id`, 1–20 `aliases`, optional 0–16 `contexts`, 0–16 `exclusions`, and 0–16 `ambiguous_aliases` (must be present among `aliases`). Every term is 2–120 characters. Validation is fail-closed.
- `terminology_version`: optional version label from the caller, echoed in annotated search hit metadata for reproducibility (e.g. `power-quality-ontology/0.1`).
- `terminology_expansion_limit`: 1–8; default 5. Independently bounded dictionary variants across the request.

Example:

```json
{
  "query": "Модернизация ПС 220 кВ: СТАТКОМ",
  "collections": ["authorized:procurement-attachments"],
  "mode": "hybrid",
  "terminology_expansion_limit": 4,
  "terminology_version": "power-quality-ontology/0.1",
  "terminology_groups": [
    {
      "id": "statcom",
      "aliases": ["СТАТКОМ", "STATCOM", "static synchronous compensator", "SVG"],
      "contexts": ["подстанция", "реактивная мощность", "ПС 220 кВ"],
      "ambiguous_aliases": ["SVG"],
      "exclusions": ["SVG vector graphics", "графические файлы SVG"]
    }
  ]
}
```

Data Platform itself expands the query into terminology synonyms, preserving the user's technical and geographic constraints, and merges results with the already-existing lexical + vector / RRF retrieval. It works with **no reasoning/LLM model configured**. The pre-existing `expand_query=true` continues to mean optional reasoning-model expansion. Explicit `query_variants` remain supported for legacy callers.

Each returned `hits[].metadata.terminology_matches` is a list of candidate groups with `id`, matched `terms`, matched `contexts` and `classification=explicit_technical_candidate`. An absent group match, including a semantically similar EPC chunk without specific equipment text, is **not proof** of that equipment's purchase. `chunk_id`, `document_id`, `canonical_uri`, original `evidence`, source hashes and consumer ACL remain unchanged. Exclusions take precedence; isolated ambiguous aliases do not match without context.

This interface is general-purpose: Power Quality, medical imaging, logistics, construction materials, IT infrastructure etc. Domain lexicons are **owned by the calling product** and sent as data. Data Platform owns validation, expansion, matching, ranking and source-level explanation. No per-tenant server-side lexicon registry or ontology authoring UI is shipped in this change; those would be separate features if needed.

## Security / limits

- No remote URL fetching, LLM calls, arbitrary regex supplied by clients, text extraction, or new permissions are caused by specifying terminology.
- Same collection permissions, consumer and tenant checks run before retrieval; federated search replays the validated groups into the overfetch request.
- Word-boundary literal Unicode matching only, no speculative acronym interpretation. Ambiguous terms such as `SVG` must be supplied via `ambiguous_aliases`, with a domain context to qualify.
- Request-bounded group/alias/variant counts and candidate retrieval limits. Combined manual + terminology (+ reasoning when enabled) variants are capped at eight in terminology searches. Tenant max-query-variants quota accounts for the additional terminology search budget; `fast` and `standard` execution modes do not permit it, while `deep` limits it to four variants. Expanded terms only influence retrieval; they never create market, winning-bidder, supplier, legal or contract value facts.
- When `terminology_groups` is missing/empty, behavior and output remain backward-compatible, including no `terminology_matches` key in individual hit metadata.
- Other components can install compatible Data Platform Python SDK **v0.4** and call `DataPlatformClient.search(terminology_groups=[...])`. Deploy SDK + server contract before switching clients; old server may ignore extra JSON keys and silently return no term metadata.

## Caveats and acceptance

This is deterministic query expansion, **not a fine-tuned semantic model**. Buried EPC technical requirements are found when indexed source chunks contain relevant aliases; actual retrieval recall depends on acquisition, extraction, chunking and ranking. Financial facts require external original protocols and signed contracts in Tender Agent/Market Intelligence. Full national procurement coverage is not measured by this feature.

Tests: `tests/search/test_terminology.py`, `tests/api/test_terminology_routes.py`, `tests/sdk/test_python_client.py`, search/hybrid legacy tests. Run with `PYTHONPATH=src:sdk/python/src` to load this local SDK, no production writes.
