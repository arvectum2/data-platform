# Search stage cohorts — source-only performance attribution (24 November 2026)

This is a bounded, privacy-preserving source change for Data Platform
issues #137 (search SLO) and #133 (ingest SLO), not a measured speedup.

## Context

PR #138 already provides per-request search stage timings and an authenticated
readiness aggregate: search_phases. The live production process observed on
24 November still did not expose that field; no staging or production
deployment or restart is part of this change.

In mixed traffic global p95 cannot distinguish lexical, vector, hybrid,
rerank or query-expansion workload mixes. This increment adds only fixed
cohorts to the existing in-memory 256-entry successful-call phase telemetry.
It does not change retrieval, ranking, tenant authorization, or SLO thresholds.

## Output contract

- The by_mode object includes only lexical, vector, hybrid, unknown. The
  unknown bucket covers old/missing/rejected labels, never arbitrary strings.
- The by_rerank_requested and by_expansion_requested objects each have
  yes and no groups. Missing legacy flag values remain absent.
- Each present cohort has samples, sufficient_samples (minimum 20),
  stage_samples, stage_sufficient_samples and stage_p95_ms. Skipped or
  unobserved stages have null p95, not fabricated zero latency.
- No query text, collection/customer/tenant/source ID, URL, credential,
  model/provider string, selected document or arbitrary metadata is retained.
  Search stage names are a fixed allowlist. Duration metrics are integers.
- Mode and feature cohorts overlap; their stage p95 values cannot be summed
  or independently prove HTTP SLO/causality or current production health.
  The existing operations.search metrics remain authoritative for complete
  HTTP request p95 and error rate, and existing targets are unchanged.
- The existing support/readiness endpoint still requires its internal key.
  No additional endpoint, capability or external authorization is added.

## Next measured experiment

After separately approved deployment under a pinned/rollback plan,
compare >=20 successful observations per relevant mode and feature cohort
to full HTTP p95 over the same observation period. Follow with an isolated
synthetic-only staging experiment on an identified costly stage. Do not
reindex originals, issue ETP actions, relax SLO or attribute root cause
from per-stage p95 alone.

Bounded synthetic tests cover 72 mixed-mode observations, unknown/invalid
cohort sanitization, 256-entry rollover, missing diagnostics, fixed numeric
data, authorized/unauthorized HTTP support GET and synthetic search POST.
No production search POST was made.
