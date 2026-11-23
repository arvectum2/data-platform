# Decision proposal — what the 10-second ingest SLO actually means

Status: **PROPOSED FOR OWNER REVIEW ONLY**. No operational threshold, alert,
release gate, consumer contract or production setting has been changed.

## Documented source of the number

- **6 Oct 2026 10:29 MSK**, git commit `f0e1834` (`feat: add operational
  SLO readiness`) introduced `src/arvectum_data/supportability.py` with
  `ingest: OperationSLO(10_000)` and `docs/SUPPORTABILITY.md` with
  `ingest p95 10 s; max error rate 1%; min samples 20`. It was merged into
  GitHub main through **PR #52** at 07:30:17 UTC that day.
- The PR #52 description calls this *operational readiness* and describes
  the 256-request rolling p95, without any reference to an external customer
  SLA, real source-size distribution or a performance/cost analysis justifying
  specifically **10 seconds**.
- Issue #133, opened **22 Nov 2026**, observes ingest p95 18.887 s and
  requires <=10s as an inherited gate. The **owner's modernization task of
  23 Nov** explicitly repeats the same criteria for Issue #133; it does
  not establish a separate external client requirement or formal service SLA.
- Therefore **10 seconds is a real, current internal operating/acceptance
  policy**, but not an immutable physical constraint. It must not be
  silently loosened in code or retroactively redefined to make readiness green.

## Why an unconditional p95 is not representative

Current `POST /v1/ingest/document` does extraction, chunking, real inference,
SQL persistence and response **synchronously**, irrespective of document size.
Readiness aggregates the last 256 HTTP ingest durations into one p95 without
tracking the corresponding chunk count or excluding background jobs.
Its error rate is the *cumulative lifetime* error rate rather than the error
rate for the same 256-request rolling window: the current dashboard mixes
observation scopes. The candidate `ingest_phases` now includes a correctly
window-scoped error rate by cohort, but does not change the original readiness
calculation or target.

Owner-approved, **isolated** 20-sample Qwen3-Embedding-4B + PG17 stage measured:

| Input | Median/individual response (indicative) |
| --- | --- |
| 2 chunks | roughly 1.65 s |
| 5 chunks | roughly 3.7–4.1 s |
| 10 chunks | roughly 8.25 s |
| 27 chunks | **24.079 s** (one observation only) |

Across these 20 synthetic TXT inputs the interpolated p95 was 9.05 s,
with 0 errors and concurrency 1. That is not the production distribution.
Independent 256-document read-only inventory had median 5 chunks and p95
**18 chunks**. Unchanged production had ingest p95 ~21–22 s (latest 256)
in the monitoring period. Neither size-conditional production latency nor
queue wait has been measured; any stronger causal claim would be premature.

## Proposed product-level SLI and SLO boundaries (not approved)

1. **Interactive/synchronous ingestion**: preserve the existing v1 API and
   deterministic IDs, auth, ACL, document source provenance, index identity,
   retry and atomic commit guarantees. Separate measurements for small
   documents (1–3, 4–8 chunks) and medium documents (9–16), at consistent
   model configuration and concurrent workload. The historical <=10s remains
   in force until a new concrete owner-approved threshold per class exists.
2. **Asynchronous/bulk ingestion**: a *new*, additive, explicitly opt-in API
   (`POST /v1/ingest/jobs`, `GET /v1/ingest/jobs/{id}` — **not yet built**).
   Acknowledgement must only be sent after the source/job is durably recorded;
   `202 Accepted` is **not** proof that the source has been indexed. Distinguish
   queued/running/completed/failed/dead_letter states with idempotency keys,
   tenant isolation, max queued bytes/concurrency, bounded retries, cancellation,
   source retention, lease/heartbeat recovery, and provenance verification.
3. **Background completion**: SLI = time from durable enqueue to searchable
   complete index (separate queue waiting and real embedding time), measured
   by 1–3 / 4–8 / 9–16 / >=17 chunk cohort, format (TXT/HTML/PDF including
   OCR escalation), consumer and worker pressure. P95 completion thresholds
   should be adopted **after** collection of representative windows and
   an explicit user/business latency budget. Do not set arbitrary numbers now.
4. **Operational readiness**: retain an overall indicator for *actual*
   critical incidents, but expose separately: API availability, intake
   acceptance, backlog age, background eventual success/error rate, and
   cohort-specific time-to-searchable. Unknown chunk counts and incomplete
   errors must not disappear from the numerator. Report each window's count,
   p50/p95, failure rate and confidence caveat (<20 = insufficient data).

## Implemented diagnostic-only candidate

The additive authenticated `/v1/support/readiness.ingest_phases` report
includes `by_chunk_count` groups `unknown_or_zero`, `one_to_three`,
`four_to_eight`, `nine_to_sixteen`, and `seventeen_plus`, each with sample
count, sufficient-sample flag, request and phase p95, and **same-cohort
rolling-window error rate**. These are explicitly **descriptive cohorts**,
not automatic per-class SLO pass/fail or an excuse to change the existing
`OPERATION_SLOS['ingest']` policy. Bounded memory (256 numeric samples), no
source contents, document IDs or secrets; API and SDK contract unchanged.

## Required owner decision and next checks

- Decide whether Data Platform is a general-purpose background knowledge
  ingestion service, a strict synchronous user-facing API, or both (with
  explicit independent service objectives). This is a product choice, not
  one that inference micro-optimizations alone can make.
- Gather at least 20 comparable *real model* observations for each important
  chunk-size and format/concurrency cohort, including 17+ chunks, with
  preserved original model/retrieval quality. Bound shared Mac mini load.
- Only after approval, update `docs/SUPPORTABILITY.md`, the SLA policy and
  tests in one coordinated change, and establish the release gate relative
  to the **approved new contract**, not by changing p95 math to pass.

**Issue #133 OPEN; production release HOLD.** No owner consent has been
sought or presumed for changing the 10-second target or adding background
production infrastructure.
