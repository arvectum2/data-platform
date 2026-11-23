# Issue #133 — production read-only observation and phase diagnostics candidate

Observation time: **2026-11-23 07:35:09 UTC**. Data obtained by one authenticated,
local **GET** to the existing production `/v1/support/readiness`. No production
POST, ingestion, reindex, model inference, process restart or configuration change.
No source text, resource names, keys, credentials or origin queries recorded.

| Operation | Latest latency window | Cumulative request count | Cumulative reported errors | p95 | Limit |
| --- | ---: | ---: | ---: | ---: | ---: |
| ingest | 256 | 8665 | 0 | **21635 ms (RED)** | 10000 ms |
| process | 256 | 2993 | 0 | 61 ms (GREEN) | 10000 ms |
| search | 256 | 330 | 0 | 248 ms (GREEN) | 1500 ms |

Readiness overall RED. Cumulative errors and the latest latency window are
not the same measurement cohort; do not fabricate window-specific error rate.
Existing issue #133 observation on 22 Nov was 18655 ms, but differing sampling
windows preclude causal change attribution.

Local read-only resource observation: 24 GiB Mac mini, used encrypted swap
about **15608 MiB**; primary embedding server at 8090 returned HTTP 200,
process startup flags include `--parallel 1`, `--ctx-size 8192`,
`--batch-size 2048`, `--threads 8`. The API health check returned HTTP 200.
The isolated second-Qwen stage's resource admission gate returned **blocked**:
`memory_headroom_low`, `memory_pressure_high_or_unknown`, and
`swap_used_too_high_or_unknown`. No model bootstrap performed.

**Conclusion:** current deployed ingest is demonstrably outside latency SLO;
CPU/memory pressure, serialized Qwen inference/queue, input-size distribution,
model wait, retry load, and PostgreSQL contention remain *hypotheses*.
Aggregated uptime counters and absent input-phase traces cannot establish
which phase caused the measured latency.

## Candidate phase instrumentation (isolated branch only)

Extend authenticated `/v1/support/readiness` with additive `ingest_phases`:

- Bounded **256 request samples**; numerical-only timings for `prepare`
  (deterministic decode/extraction and chunking), `lookup` (read-only SQL
  session), `embedding` (provider calls + retries and queue wait), `persist`
  (fresh SQL session, upserts, commit), and independent whole HTTP request time.
- Report p95 and cohort sample counts by **input byte-size bucket** and
  **observed ingress concurrency**. Distinguish `<20` samples as insufficient
  diagnostic evidence. Never sum unrelated percentile values to infer total.
- Record total chunk count and embedding call attempts, but no document text,
  filenames, URI, collection/consumer ID, request ID, SQL string or credential.
- `ContextVar` attaches each request's mutable trace to its own copied worker
  context; SQL sessions and retry paths keep existing behavior. No new network
  probes or external telemetry destinations.
- This addition does NOT change the production SLO threshold, overall SLO
  status semantics, embedding model or transactional data contract.

## Isolated verification

- New isolated PostgreSQL17 real HTTP E2E with hashing provider: real ingest,
  idempotent index, vector/hybrid/lexical search, ACL, Python SDK, restart,
  simulated provider failure and successful retry after restoring provider,
  code rollback to PR #134 and forward recovery; numeric-only authenticated
  timing endpoint produces non-empty prepare/lookup/embedding/persist spans.
- A synthetic `40 ms` embedding-provider wait is correctly assigned to
  `embedding`, not to SQL; reported whole-request time includes the delay.
- Unit checks cover phase isolation, source-content redaction, minimum window,
  exception-path timing and AnyIO worker ContextVar propagation.
- Full Ruff / pytest and exact-head protected GitHub CI required before review.

## Next gate (not executed)

1. Review candidate diagnostics and release risk independently; do not treat
   this doc as authority to switch production.
2. Only after separate owner approval, deploy in an explicit maintenance
   window with saved version/DB backup and rollback verification.
3. Collect representative, warmed, same-model production-class phase windows,
   at least 20 observations per selected cohort, capture actual CPU/swap,
   queue wait and transaction wait; contrast serial and bounded concurrency.
4. Fix the *measured* bottleneck in a separate branch, then re-run all
   independent consumer/SLO gates and obtain explicit release approval.

Production and Tender Agent Core release stay HOLD pending real p95 <=10s,
error rate <=1%, safe shared-host resource envelope and Owner approval.
