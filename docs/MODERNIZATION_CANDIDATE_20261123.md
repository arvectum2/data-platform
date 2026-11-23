# Data Platform modernization candidate — 23 Nov 2026

Release status: HOLD. All checks below were isolated; no production restart,
Qwen/Reranker change, migration, reindex, production data write or deployment.

## Exact baseline and scope

- GitHub main: b2bd8a5ce7aa3a438ee5af240c249afe1fc9e473.
- Parent Draft PR #134 HEAD: 7eb86bd3da350ef3318790ce07b6a28aadac267e.
- Production checkout: cd40a5040ef64afa27515697a7e3802314ee36ab, Python 3.12.14.
- Local canonical checkout: 38322fd5f1cbec2d377c478d9980cae2382366a0 (different from main).
- Branch chore/dp-product-modernization-20261123 builds on PR #134 in an
  isolated worktree. All other branches, worktrees, services and data remain intact.

## Runtime / dependency comparison

| Runtime / package | Previously | Candidate |
| --- | --- | --- |
| Python development default | 3.12 | 3.14 |
| Python CI | 3.11, 3.12, 3.13 | 3.11 through 3.15 |
| Node.js SDK CI | 20 | 20, 22, 24, 26 |
| FastAPI | 0.143.0 | 0.165.0 |
| Starlette | 1.7.0 | 1.10.0 |
| Pydantic | 2.14.0 | 2.14.4 |
| pydantic-settings | 2.15.0 | 2.16.3 |
| SQLAlchemy | 2.1.4 | 2.1.9 |
| Alembic | 1.20.0 | 1.20.1 |
| Psycopg | 3.3.6 | 3.3.9 |
| pypdf | 6.20.0 | 6.21.4 |
| python-multipart | 0.0.32 | 0.0.34 |
| Ruff | 0.17.0 | 0.17.6 |
| openpyxl | 3.1.5 | unchanged |
| cryptography | 46.0.7 | 50.0.2 (OSV security remediation) |
| pytest | 8.4.2 | 9.2.0 (OSV security remediation) |

CI actions were also modernized to the official latest releases verified on
GitHub on 2026-11-23: checkout v7.0.1, setup-node v7.1.0 and
setup-python v7.1.0 (instead of deprecated Node 20 action runtimes).

Python >=3.11 and Node engines >=18 are preserved for existing clients;
Python 3.15 passed locally but is not the default. Python and JavaScript
SDK package versions and HTTP consumer contract 1.x were not changed.
Optional lock updates include Playwright 1.65.2, sentence-transformers 6.3.0,
transformers 5.24.0, torch 2.15.0, huggingface-hub 2.4.0. Their licenses,
compatibility, telemetry and sidecar resource envelope require independent
validation before optional runtime promotion.

## Performed checks

- uv lock consistency: PASS; installed fresh from frozen lock.
- Ruff: PASS.
- Full pytest: PASS separately on Python 3.11.16, 3.12.14, 3.14.10, 3.15.2;
  PostgreSQL-only cases intentionally skipped without disposable DB.
- Python SDK 0.4.0 editable installed and its tests passed.
- JavaScript SDK: 9/9 PASS on Node 26.13.1.
- Actual PostgreSQL17/pgvector disposable integration: 35 PASS, 1 expected
  CI-identity-only SKIP, in container limited to 384 MiB and 1 CPU on loopback
  127.0.0.1:15543; test DB identity verified before migrations. Container removed.
- Original 2026-11-23 candidate SHA e8052579: GitHub CI **11/11 PASS**,
  GitVerse mirror HEALTHY. Expanded 12-job workflow with actual HTTP E2E and
  dependency security fixes requires fresh exact-SHA CI before claiming PASS.
- Tender Agent focused SDK / RAG / knowledge boundary tests on its unchanged
  working tree: 33 PASS. Real candidate HTTP exercised with Python SDK in
  disposable E2E; Arvectum OS/Growth full consumer parity remains pending.
- Qwen synthetic isolated stage: BLOCKED by resource governor: memory headroom,
  memory pressure and swap. No second model started.

## Roadmap / acceptance

The canonical docs/ROADMAP.md is protected by the native-roadmap-review
source-integrity gate. This PR preserves its exact existing bytes and records
the proposed modernization roadmap below instead. A canonical roadmap edit
requires separately reviewed source authorization; this review does not
forge approval or bypass that gate.


P0 Issue #133: remains OPEN. PR #134 provides a tested, not-deployed DB
transaction lifetime fix. Reported real ingest p95 above 10s remains RED,
and isolated hash/PG timings cannot prove live production SLO. Require >=20
representative samples, p95 <=10s, <=1% error rate and documented load/window.

P1 DP-MACMINI-E2E-STACK-001: partially covered by disposable PostgreSQL tests
for migrations, ingestion, identity reuse, hybrid search, ACL, provenance,
transactions and index revisions. **New** isolated actual HTTP E2E also PASSED:
20 synthetic hashing ingests, consumer SDK, ACL, index revision, concurrent
ingestion, failure recovery, graceful restart, source rollback to PR #134 and
forward restoration. This is mocked embedding, not real Qwen/answer/24GB soak;
the original broader roadmap item remains OPEN.

P2 DP-INT-002: real KnowledgeAssetRecord acceptance remains OPEN for missing
genuine upstream data. Model promotions, distributed crawlers, hosted services
and billing activation remain deferred pending explicit business decisions.

## Future maintenance window (instructions only; not executed)

1. Require exact final green protected CI, consumer parity, synthetic E2E and
   representative SLO gate plus explicit owner authorization.
2. Preserve current production checkout cd40a5040ef64afa27515697a7e3802314ee36ab,
   Python 3.12.14 environment, PostgreSQL backup, index/model identities and
   source-evidence contract before any switch.
3. Validate candidate in a separate runtime with a disposable DB and distinct
   loopback port, then validate API/SDK contracts and startup/shutdown/restart.
4. Change production checkout only in the approved window and monitor p95,
   error rate, resource pressure and Tender Agent citations; never reindex as
   a side effect of runtime version change.
5. If the release gate fails, restore the saved checkout and its environment,
   validate previous API and consumers, and do not silently change retrieval
   backends or attempt destructive schema downgrade.

Additional checks: frozen-lock package provenance 99 PyPI registry entries,
zero affected packages in post-fix OSV batch on 2026-11-23; see
`docs/DEPENDENCY_AUDIT_20261123.md`. Corrected synchronous usage metering
in ASGI middleware by moving DB work to threadpool; unit regression PASS.
Canonical roadmap source is unchanged; see separate
`docs/MODERNIZATION_ROADMAP_PROPOSAL_20261123.md`.

Candidate is reviewable after exact protected CI; release is HOLD meanwhile.

## 23 Nov read-only production diagnostic follow-up

A fresh authenticated GET (no production mutation) observed **ingest p95
21635ms / latest 256 samples / 8665 cumulative requests / 0 cumulative
errors**, while process p95 was 61ms and search p95 248ms. Mac mini used
~15.6GiB swap; isolated second-Qwen admission refused. The cause remains
unknown; single-slot Qwen is a hypothesis, not proven attribution. The branch
adds bounded numeric-only `ingest_phases` telemetry and a 40ms synthetic
provider-delay attribution check in isolated HTTP/pgvector E2E. Full receipt,
limitations and future owner-gated acceptance conditions are in
`docs/INGEST_P95_READONLY_TRIAGE_20261123.md`.

This telemetry is **not deployed**. Real production p95 remains RED; do not
interpret synthetic phase timing or hashing p95 as Qwen acceptance.
