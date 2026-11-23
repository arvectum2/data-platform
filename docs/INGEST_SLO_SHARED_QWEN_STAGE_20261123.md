# 23 Nov 2026 — controlled shared-Qwen ingest stage (Issue #133)

Status: **isolated real-model HTTP stage PASS; PRODUCTION SLO still RED/HOLD.**
Owner explicitly authorized a short test window for pausing future Tender Agent
background ingest starts, using the existing Qwen server and disposable DB.
No real files, source identifiers, tenant content, service reconfiguration,
Qwen restart, production DB writes, production reindex or deployment.

## Environment and safety

- Date window: **2026-11-23 08:06:14–08:08:13 UTC** (bounded including setup
  and scheduler hand-off); local Mac mini M4 Pro 24 GiB.
- Candidate worktree, no production deployment. Fresh, identity-verified,
  loopback-only PostgreSQL17/pgvector container with **384 MiB memory / 1 CPU**,
  randomly generated DB owner/name/port and `alembic upgrade head` performed
  only against that disposable database. Test HTTP API separately bound to
  loopback on a random port with authenticated requests and stage-only API key.
- Existing **Qwen3-Embedding-4B** llama.cpp server at `127.0.0.1:8090/v1`,
  dimension **2560**, inference batch **8**, no extra model process.
- Temporarily disabled *future* `launchd` starts of
  `com.arvectum.tender-agent-technical-sibur`, first letting its running
  invocation finish; did **not** stop the persistent research executor, Qwen,
  Data Platform, Tender backend, PostgreSQL or their application processes.
  The test's finally handler restored the launchd enabled state, with a
  failsafe to restore it if the test was interrupted.
- Live health remained HTTP200 for Qwen, Data Platform, reranker, Tender Agent;
  after the test, that periodic scheduler was **enabled and running**,
  ephemeral container count **zero**, and used swap had **not increased**.
- Existing real-model governor for a **second Qwen** remained inapplicable:
  no additional model was launched, GPU/memory guard not circumvented.

## Input validity and method

A preliminary 20-sample stage had a bad synthetic text generator: repeated
identical phrases deduplicated long documents to only 2–3 chunks. That stage
was **rejected**, not used for acceptance. It still completed without errors;
all temporary resources were cleaned and scheduled launches restored.

Fixed generator creates uniquely numbered Russian technical paragraphs. Before
running HTTP, the exact `ingest_bytes` chunker was exercised offline on all
20 synthetic inputs, proving a chunk count range **2–27**, median **5**.
Each runtime HTTP ingest checked its chunk count against the offline preflight
expectation to prevent silent deduplication or contract drift.

Requests were strictly **sequential (concurrency 1)**. A fresh unique source
was ingested for each request using the real `/v1/ingest/document` route and
existing model, then the authenticated aggregate-only
`/v1/support/readiness.ingest_phases` was read before removal of disposable DB.
No private input or identifiers were stored in the numeric report.

| Synthetic byte length | Observations | Chunks each | Actual HTTP wall time |
| --- | ---: | ---: | ---: |
| 5 KiB (approx.) | 9 | 2 | 1629–1706 ms, apart from one 1642 ms |
| 11 KiB (approx.) | 8 | 5 | 3734–4062 ms |
| 22 KiB (approx.) | 2 | 10 | 8246 and 8259 ms |
| 62 KiB (approx.) | 1 | 27 | **24079 ms** |

Actual generator requests used byte targets `5000`, `11000`, `22000`, `62000`;
UTF-8-safe truncation could lower size by up to a few bytes. Different
size/concurrency cohorts do **not** have 20 samples each.

## Outcomes

| Metric | Observed | Interpretation |
| --- | ---: | --- |
| Completed HTTP ingests | **20/20** | All succeeded |
| HTTP errors | **0** | Zero among this short synthetic series |
| Request p50 | **3742 ms** | Synthetic only |
| Request p95 | **9050 ms** | Under numeric 10000ms target **in this series only** |
| Request maximum | **24079 ms** | 27-chunk document exceeded 10s |
| Per-stage `embedding` p95 | **8952 ms** | Includes inference calls, queue wait, retry logic |
| Per-stage `prepare` p95 | **3 ms** | Text extraction/chunk creation |
| Per-stage `lookup` p95 | **8 ms** | Read transaction and existing vectors lookup |
| Per-stage `persist` p95 | **96 ms** | Write transaction + SQL upserts + commit |
| Inference **batch attempts** | **25** | 20 ingest requests, multi-batch larger documents; not 25 retries |
| Source chunks | **105** | 9×2 + 8×5 + 2×10 + 27 |

Statistics follow the existing Data Platform interpolated-percentile function.
Individual phase p95 values must **not** be added together: their peaks may
occur in different requests. Stage timings independently expose provider wait;
they do not distinguish inference CPU from external queueing at the Qwen
server. The one 27-chunk sample dominates the long tail, but has limited
influence on interpolated p95 of only 20 observations.

**Critical limitations:** this is not production SLO proof. Production was not
upgraded to the instrumented candidate; its latest readiness still reported
**RED, ingest p95 21635ms / latest 256** at 08:09:15 UTC, 8687 cumulative
requests, zero cumulative recorded errors. The production HTTP latest latency
window is not paired with these synthetic document sizes or phase timings.
Real stored document inventory (independent read-only sample of 256) has
median **5 chunks** and p95 **18 chunks**, whereas this synthetic series has
median **5** and p95 around **10–11** chunks. The benchmark's representative
long tail, concurrency, source formats and duty cycle are NOT established.
The persistent research executor was not forcibly paused; competition for the
shared Qwen queue was not fully excluded. No source text was collected.

## Next engineering decision

Strong staging evidence identifies **embedding provider time** as the dominant
elapsed phase. Avoid indiscriminate SQL tuning or loosening SLOs. Proceed with
isolated, non-production improvements that reduce inference cost or queue wait
while preserving indexing contract, source provenance, dimension 2560 and
search relevance. An independent memory-safe real workload/soak gate, full
consumer regression and explicit Owner release authorization are still needed
before production code/config/model change. Issue #133 remains OPEN.
