# Data Platform modernization — canonical roadmap review proposal

Date: 2026-11-23. **Proposal only**: `docs/ROADMAP.md` is an integrity-pinned
native source. Its source revision/checker requires separately reviewed
authorization; this change intentionally leaves all original bytes intact.
Do not mark unchecked roadmap tasks DONE based on synthetic fixtures.

| Source ID / scope | Verified candidate evidence | Proposed disposition |
| --- | --- | --- |
| DP-MACMINI-E2E-STACK-001: persisted isolated DB/API stack | 20 synthetic HTTP ingests; real PG17 migrations, lexical/vector/hybrid, ACL, evidence, retry-fail-closed via provider restart, index revision, API restart, rollback to PR #134 and forward recovery | Record the isolated **hashing/mock subset as verified**; the original item is broader and stays OPEN pending real Qwen, answer, long-duration soak |
| DP-INT-001: Tender Agent consumer boundary | 33 targeted Tender Agent tests PASS; actual Python SDK against disposable candidate HTTP service PASS | Preserve existing COMPLETE. Full candidate-specific production-equivalent Tender Agent workflow parity still pending |
| DP-INT-002: Arvectum OS real-data gate | No authorized non-empty real KnowledgeAssetRecord input supplied | OPEN. Never manufacture real upstream records |
| Issue #133: production ingest p95 | PR #134 transaction-lifetime fix regression PASS; synthetic hashing p95 ~10 ms; old real p95 18.655 s | HOLD; require >=20 representative real-inference observations, p95 <=10 s, error rate <=1%, measured phase breakdown |
| DP-MACMINI-E2E-STABILIZATION-002: combined EIS/Gemma | No new combined real acceptance | OPEN; prior execution safety constraints intact |
| DP-MODEL-REFRESH-RU-001 / DP-MODEL-REFRESH-001 | No new benchmark or model rollout | Retain current checkboxes; larger RU gold corpus and optional model promotion still OPEN |
| Product-first dependency/runtime modernization | Python default 3.14, Python 3.11–3.15 and Node 20/22/24/26 CI, locked provenance/security and release regression | Candidate READY FOR REVIEW only; production HOLD |

Native-roadmap-review status is not a release authorization. A separately
reviewed source revision must preserve all task IDs/history and satisfy the
integrity/criterion-specific evidence gate before altering source statuses.
