# DP ingest p95 — synthetic staging evidence procedure

This is a read-only analysis tool for Data Platform issue #133 and the Tender Agent Core runtime gate. It is not an ingestion worker, source collector, production profiler or release authorization.

## Baseline and limits

On 22 Nov 2026, authenticated GET-only support readiness observed ingest p95 18,887 ms over the latest 256 samples, against the documented 10,000 ms ceiling. Cumulative errors: 0 of 7,989 ingest requests. This does not identify the slow phase, prove steady-state error rate over that exact latency window, or establish root cause.

## Synthetic-only staging input

A separately authorized disposable staging environment must use a fixed, documented embedding model/configuration, separate collection/storage and generated non-sensitive bytes. Never replay customer documents, EIS originals, credentials, source IDs, private filenames, real collections or production data. Do not run a production ingest or reindex.

For each completed synthetic request record one JSONL line containing ONLY:

- synthetic: boolean true, asserted by trusted staging producer
- bytes: generated input size (>0)
- chunks: produced chunk count
- concurrency: concurrent synthetic requests (>0)
- retry_count: embedding retries beyond initial attempt
- status_code: final HTTP code
- total_ms: full request wall time
- decode_ms: exclusive extraction/decode span
- chunk_ms: exclusive splitting/tokenization span
- embed_ms: exclusive vector inference plus retry time
- db_ms: exclusive persist/upsert/commit span

All timings are nonnegative integer milliseconds. The four phases are disjoint and their sum cannot exceed total_ms. Other request overhead is the remainder. Synthetic source/model/build provenance belongs in a separate PRIVATE staging manifest; the analyzer intentionally rejects textual identifiers, URLs or any unexpected fields.

Example valid line (repeat for authorized synthetic observations):

    {"synthetic":true,"bytes":8192,"chunks":3,"concurrency":1,"retry_count":0,"status_code":200,"total_ms":9050,"decode_ms":200,"chunk_ms":150,"embed_ms":7500,"db_ms":350}

Local offline command, AFTER authorized staging measurements:

    python scripts/ingest_slo_staging_analysis.py --synthetic-jsonl /path/to/approved-synthetic-only.jsonl

The script performs no network calls, SQL operations, service changes or filesystem writes. It emits only aggregate cohort statistics and refuses unexpected/identifying fields, trace files larger than 5 MB or more than 10,000 observations. It never outputs the input path or original lines.

Fewer than 20 observations means insufficient-data. Every size/concurrency cohort has its own >=20 observation gate. Synthetic green requires p95 <=10,000ms and error rate <=1%. Percentile interpolation matches existing Data Platform SLO. Every report unconditionally has production_slo_proven=false, even if synthetic evidence is green.

## Remaining acceptance

1. Independently approve synthetic staging environment, resource budget, model pin and expiry; keep production and private originals untouched.
2. Collect >=20 observations PER chosen size/concurrency cohort with documented UTC window, same warm-up policy and exclusive phase instrumentation.
3. Compare stage latency, retry distribution, file size and CPU/memory/thermal telemetry. Correlation alone is not root cause.
4. If measured evidence supports it, patch the bottleneck and run negative/concurrency regressions plus protected exact-head CI.
5. Separately demonstrate sustained representative production ingest p95 <=10 seconds, <=1% errors, SDK/HTTP reliability, real Gemma source acceptance and explicit Owner approval before any runtime switch.

No production deployment, relaxed SLO, paid action, procurement platform access, backup pruning, automatic bid or extra Watchdog is authorized.
