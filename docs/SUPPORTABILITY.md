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
