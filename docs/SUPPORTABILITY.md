# Operational SLOs and supportability

Data Platform exposes bounded, secret-free operational readiness through two internal endpoints:

- GET /v1/status — cumulative request/error/latency counters plus rolling p95 over the latest 256 requests per operation;
- GET /v1/support/readiness — SLO evaluation for the same operation classes.

Both endpoints use the normal internal-key boundary when one is configured. The support payload contains no query text, document text, fetched URLs, API keys, database URLs or exception messages.

## SLO policy

| Operation | p95 target | max error rate | minimum samples |
| --- | ---: | ---: | ---: |
| process | 10 s | 1% | 20 |
| ingest | 10 s | 1% | 20 |
| search | 1.5 s | 1% | 20 |
| answer | 20 s | 1% | 20 |
| research | 120 s | 1% | 20 |
| discover | 5 s | 1% | 20 |
| extract | 10 s | 1% | 20 |
| reindex | 120 s | 1% | 20 |

These are operational service ceilings. Search execution-mode budgets remain stricter where applicable, for example FAST at 500 ms.

Readiness states:

- green: at least 20 recent samples and both latency/error targets pass;
- red: enough samples exist and either target is breached;
- insufficient-data: the rolling window is too small to make an SLO claim.

Overall readiness is red if any sampled operation is red, green when at least one operation is green and none are red, otherwise insufficient-data.

## Support workflow

1. Check /health to verify the process is alive.
2. Check /v1/status for database/index/model identity and bounded operation counters.
3. Check /v1/support/readiness for SLO state and the operation that breached.
4. Probe /v1/models/status?probe=true only when a model-backed stage is implicated.
5. Use request IDs to correlate logs. Do not copy prompts or documents into support tickets unless the customer explicitly supplies them for debugging.

The rolling latency window is intentionally bounded and in-memory. It is not a billing ledger or long-term telemetry store.

## Background document ingestion (opt-in candidate)

`POST /v1/ingest/jobs` returns `202 Accepted` only on **durable enqueue**;
that receipt does not prove the document is searchable.
`GET /v1/support/ingest-jobs` separately reports queue depth/age and p95
from enqueue until indexed completion, with sample sufficiency and error
fraction. It does not change the existing synchronous ingest <=10s p95 or
overall readiness. No background latency target has yet been approved.
Default OFF, requires a separate worker and migration. See
`docs/ASYNC_INGEST_CANDIDATE_20261123.md`.

## Search phase attribution (source-only candidate, 24 November 2026)

The search operation's HTTP readiness remains authoritative: p95 target 1,500ms,
minimum 20 requests, error rate at most 1%. If this source candidate is
independently approved and deployed, the existing GET /v1/support/readiness
additionally exposes a separate search_phases numeric snapshot from completed,
successful search executions. This is not enabled on the previously running
production release merely by merging code.

It captures only fixed names and rounded, finite numeric durations already
produced by the search engine: query-expansion, terminology-expansion,
embedding-query, lexical-retrieval, vector-retrieval, fusion, product-ranker,
rerank, total-search. A ring buffer retains at most 256 successful responses.
Skipped/unavailable stages are not recorded as false zeroes. Per-stage sample
counts and their own 20-sample sufficiency are explicit.

No query text, document content, snippets, source/collection IDs, URLs,
provider/model names, request metadata, customer information, secrets, or
exception text enters this buffer or its support summary. Only the
aggregate sample counters, p95 and a no-content indicator are returned.

Per-stage total-search latency is measured inside the search engine and
excludes HTTP transport, application serialization and middleware overhead.
Stage-specific p95s are independently distributed and do not sum to an
HTTP p95. Search execution errors are still counted by the existing
HTTP operation SLO, but failed calls without completed stage diagnostics
are not included in this successful-execution phase breakdown.

The observed 24-Nov production GET-only snapshot was search RED (p95
10,086ms / 40 samples; target 1,500ms; zero API errors). Source-only
instrumentation cannot establish root cause or production improvement by
itself. No synthetic search/model requests, provider changes, reindex,
database mutation, or production service restart were performed for this
candidate. Real-model capacity admission, upstream protected CI, independent
representative SLO proof and owner deployment approval remain mandatory.

See issue arvectum2/data-platform#137 and the separate earlier ingest SLO
issue #133. A green rolling ingest sample does not close the search problem.
