# Dependency source, license and advisory review — 2026-11-23

Scope: isolated Data Platform modernization candidate; **not** a production
runtime or model rollout. All checks used only package names and versions.

## Trust and vulnerabilities

- Source inventory: 100 universal-lock entries: 99 `https://pypi.org/simple`
  entries and one editable project root. Some names occur more than once in
  the universal lock due to environment-specific resolutions; this is expected.
  No alternative package registry, direct VCS dependency or URL wheel was found.
- Checked 99 locked PyPI entries via `https://api.osv.dev/v1/querybatch`.
- Initial findings: `cryptography 46.0.7` matched seven OSV advisory IDs
  (GHSA-537c-gmf6-5ccf, GHSA-g6cj-pr64-35w5,
  GHSA-jwv3-5hgf-82ww, GHSA-m2h6-j472-rp4c and three associated
  PYSEC-2026 IDs); `pytest 8.4.2` matched two overlapping records for
  vulnerable tmpdir handling (GHSA-6w46-j5rx-g56g and PYSEC-2026-1845).
- Resolution: bound `cryptography>=50.0.0,<51.0` and `pytest>=9.0.3,<10.0`;
  regenerate `uv.lock`: `cryptography 50.0.2`, `pytest 9.2.0`.
- Post-fix OSV query: **99 returned / 0 package entries reporting a known
  vulnerability**, as of 2026-11-23. This is a point-in-time database check,
  not a proof that no vulnerability exists. A network-free lock regression
  test prevents the known vulnerabilities and unreviewed origins returning.

## Declared upstream licensing

PyPI version-specific public metadata was queried for the following packages.
These are declared labels, *not* an exhaustive legal review of bundled code:

| Package family | Declared license / expression |
| --- | --- |
| FastAPI / Pydantic / SQLAlchemy / Alembic | MIT |
| Starlette / Uvicorn / pypdf / HTTPX / xlrd | BSD family |
| psycopg | LGPL-3.0-only (compliance review before redistributing binaries) |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| python-multipart | Apache-2.0 |
| openpyxl | MIT |
| Playwright / sentence-transformers / Transformers / Hugging Face Hub | Apache-2.0 (declared) |
| Torch | Multiple declared bundled licenses including Apache/MIT/BSD/BSL/ISC/Zlib |
| Ruff / pytest / pgvector | MIT |

## Privacy, availability and safety bounds

- The core can use local PostgreSQL/pgvector and deterministic hashing; no
  outbound inference or automatic telemetry service is introduced by these
  dependency-only changes. Optional library runtime behavior has **not** been
  independently audited for all potential external calls or subprocesses.
- No Playwright browser install, hosted AI API credential, remote model,
  embedded model dimension or reranker version was promoted.
- Actual package/index access from a Russian network, complete transitive
  license obligations, native wheel supply-chain reproducibility, browser
  downloads and Linux CUDA artifact audit **remain unverified**.
- All existing model/consumer release gates remain in effect. Do not use this
  report as authorization to promote the optional ML extras in production.
