# Arvectum Data Platform 0.5.0

Release date: 2026-10-04

## Scope

0.5.0 is the first production-accepted multi-consumer Data Platform release. It keeps the platform in the 0.x series while adding backward-compatible public HTTP/search capabilities and production operational controls.

## Source provenance

Promoted/generalized source baselines:

- Discount Parser: `arvectum2/discount-parser` at `4bde0909d18b`
  - initial canonical Data Platform cutover: `a591256f50a21b8618639129eccb15eb214204d5`
  - Discount Parser consumer cutover: `e0e303999e8fb1c2d6665f9013d3ad0d7ea1c2d7`
- Tender Agent: `arvectum2/tender-agent` at `3bbca3dc615baedefe645c0ed0036d6534d12998`
  - Tender Data Platform retrieval integration: PR #144 / merge `cbd5275`
  - Arvectum OS/Tender follow-up integration: PR #147 / merge `b40cb2b`

Product/domain logic remains in consumer repositories.

## Major additions since 0.4.0

- PostgreSQL FTS + pgvector hybrid retrieval with weighted RRF.
- Versioned collections, deterministic revisions and idempotent/atomic rebuilds.
- Pre-chunked ingestion for consumer-owned canonical chunks.
- Canonical URI filtering and optional page-level canonical collapse.
- Bounded consumer-controlled query variants.
- Authorized federated cross-collection search with consumer-scoped keys.
- Relevance evaluation harness and frozen production benchmarks.
- Durable relevance feedback capture without storing raw query text.
- Deterministic ambiguity-safe entity resolution.
- Provenance-aware, idempotent entity relations.
- Runtime operation metrics and secret-free diagnostics.
- Capacity guardrails, embedding retry/dead-letter recovery.
- PostgreSQL backup/restore helpers with checksum verification.
- Production Mac mini runtime under launchd.

## Production consumers

### Tender Agent

Production retrieval uses Data Platform hybrid search while Tender Agent retains EIS/44-FZ/223-FZ semantics, procurement chunks, citations and analysis policy.

Pilot registry `0187200001726001304` was accepted with:

- 60 resources / 60 documents / 60 chunks / 60 embeddings;
- readiness = true;
- hybrid retrieval mapped back to canonical Tender chunks;
- retrieval-only fast analysis: 10 sections / 16 sources / no warnings or errors;
- semantic-first Tender profile matched the isolated legacy semantic baseline top-1 on 5/5 representative questions.

### Arvectum Site / Growth

Accepted consumers include:

- first-party site collection;
- external research collection;
- public product metadata collection;
- authorized site + product federation;
- product/organization entities and publishes relation;
- preferred SEO landing policy kept in the consumer repository.

The frozen Data Platform Search Console baseline contains 12 real Google/Yandex intent formulations. Raw platform retrieval remains a measurement layer; intentional SEO landing routing remains a Growth consumer policy.

### Discount Parser

The reusable acquisition/extraction engine was promoted into the canonical `arvectum-data` package and the vendored duplicate removed only after consumer acceptance.

## Search quality evidence

Accepted production benchmarks include:

- `production_acceptance_v1`: 9/9 top-1, MRR 1.0;
- `production_acceptance_v2`: 10/10 top-1, MRR 1.0, including authorized federation;
- `lexical_exact_v1`: hybrid 1.00 top-1 / 1.00 MRR, outperforming vector-only and lexical-only modes;
- `growth_search_console_v1`: intentionally preserved raw baseline at 0.50 top-1 / 0.583 MRR before consumer landing policy.

Current evidence does not justify replacing PostgreSQL FTS with BM25.

## Security and privacy invariants

- Search is collection-scoped.
- Federated search fails closed on unauthorized collections.
- Consumer federation keys are separate from the general internal API key.
- Status/metrics do not expose DB URLs, keys, query text, fetched URLs or exception messages.
- Relevance feedback stores only a SHA-256 query hash, not raw query text.
- Entity resolution never auto-merges ambiguous aliases.
- Entity relations are explicit and provenance-aware.

## Deliberately deferred

The following remain backlog-only until benchmark/consumer evidence justifies them:

- BM25 backend;
- learned reranker;
- bounded LLM reranker;
- automatic/domain-agnostic query expansion;
- distributed crawling.

The 0.5.0 API does expose bounded consumer-supplied query variants, but Data Platform does not invent domain synonyms itself.

## Release gate

Verified on 2026-10-04 before tagging:

- Data Platform lint and full test suite: PASS;
- live PostgreSQL API integration on an isolated pgvector:pg17 database: PASS;
- Discount Parser full regression suite: PASS;
- Tender Agent fresh origin/main RAG/Data Platform regression: 142 passed, 8 skipped;
- Arvectum Site Data Platform intent, repository, JavaScript and sitemap checks: PASS;
- production_acceptance_v2: 10/10 top-1, MRR 1.0, hit@5 1.0, mean recall@5 1.0, about 131 ms p50 and 146 ms p95;
- GitHub/GitVerse SHA parity is required immediately before and after tagging.
