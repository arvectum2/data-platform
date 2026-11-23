# Controlled Qwen3-Embedding-4B ingest/async A/B window — not yet authorized

23 Nov 2026. This plan is **offline preparation only**, not a runtime acceptance result, new SLO, or authorization for an additional benchmark window. The Mac mini currently runs shared Qwen3-Embedding-4B Q8_0 for production Tender Agent and Data Platform, with high swap usage. Do not start a second embedding model, bypass the resource governor, or pause production launches outside a separately approved short window.

## Preflight proof, completed without Qwen

`scripts/ingest_qwen_cohort_preflight.py --check-only` generates unique, synthetic Russian technical source text and validates the **actual** `ingest_bytes` chunk counts, not merely raw file sizes. It prints only lengths/counts and cannot invoke inference, Docker, PostgreSQL or launchctl. The verified targets are:

| Exact chunks | Approx synthetic UTF-8 size |
| ---: | ---: |
| 5 | 9,674 bytes |
| 10 | 21,314 bytes |
| 18 | 39,912 bytes |
| 27 | 60,823 bytes |

The values are valid for the current chunking defaults and seeds; run the deterministic check again after processing changes. They are **not** Qwen latencies.

## Future A/B protocol (not executed)

- Compare actual HTTP ingest and **durable enqueue → searchable completion** with the same pinned Qwen3-Embedding-4B model, embedding dimension 2560, PostgreSQL17/pgvector disposable index, source provenance and consumer ACL.
- For each chunk cohort 5/10/18/27 and each concurrency stratum 1/2, collect >=20 independently identified synthetic jobs: **160 total** at the stated minimum. Record request ACK latency, queue waiting, inference and persistence phase times, completion p50/p95/max, model errors, retried jobs, ready-to-search assertions and resource pressure. Keep comparable ordered cohorts and a randomised sequence to avoid scheduling bias; do not generalise from a single 27-chunk observation.
- Define explicit resource governor limits beforehand (swap growth, memory pressure, Qwen p95 impact, production HTTP health, time budget) and immediately abort if breached. Use only the existing authorised one-window scheduler pause mechanics with independent restoration/failsafe. Do not change Qwen model flags, GPU offload or weight precision until a different controlled change is approved.
- Keep retrieval relevance, citations/ACL, source hash integrity and stable 2560-dimensional index contract. A fast answer with corrupted sources or missing evidence is a regression. The separate background SLO numbers are to be proposed from representative results and approved by the owner; the legacy synchronous <=10 s remains in force until changed explicitly.
- Production deployment remains blocked on DP PR #135 review, Tender Agent PR #729 SDK compatibility + durable progress integration, backup/retention/rollback readiness and explicit owner release gate. No live Qwen load is part of this offline preflight.

**No 160-sample load was run.** Issue #133 OPEN; production HOLD.
