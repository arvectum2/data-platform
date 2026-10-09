# Tender Agent on Mac mini — internal launchd runtime and live E2E

Date: 2026-10-09. Target: Apple Silicon Mac mini with 24 GiB unified RAM.
Canonical source remains `/Volumes/ArvectumSSD/Arvectum/repos/tender-agent`.
No existing Tender Agent source branch was modified as part of this operation.

## Reliable 24/7 runtime

The previously active Python backend `:8001` was an orphan
(PPID=1, booted under a former launcher); `launchctl list` showed
`com.arvectum.backend` had failed. The old Node launcher:
`/Users/master/.local/bin/tender-agent-backend-node.cjs`
blocked in `git rev-parse HEAD` against the external SSD, followed
by macOS TCC `Operation not permitted` when launching a bash script
from the external volume. A fallback Git-probe patch alone was
**insufficient**; this is not an EIS/LLM-only problem.

**Final installed solution:**
- Copy the runtime source into **internal APFS**:
  `/Users/master/arvectum-runtime/tender-agent` (~184 MiB; source,
  scripts, migrations, venv and public demo fixtures).
- Fix the installed editable `.pth` in the copied venv to point to the
  internal source directory, not the original SSD repo. A leftover
  `__editable__.ai_corporation-0.1.0.pth` initially caused the
  Python process to hang inside `opendir()` on the SSD.
- Keep runtime credentials ONLY in
  `/Users/master/Library/Application Support/Arvectum/tender-agent/runtime.env`
  (mode 0600; **never commit or print them**). Original private
  SSD config preserved.
- Existing launchd label **`com.arvectum.backend`** now runs
  `/bin/bash /Users/master/arvectum-runtime/tender-agent-backend-launch.sh`
  and Python/uvicorn through its internal venv. This bypasses the
  Node+Git startup blocker without disabling any required services.
- Original launchd plist backed up as
  `~/Library/LaunchAgents/com.arvectum.backend.plist.bak-20261009-node-launcher`;
  original Node wrapper backed up as
  `~/.local/bin/tender-agent-backend-node.cjs.bak-20261009-git-probe`.
- The final launchd process independently served `:8001/health`
  HTTP 200 after 11 probes, and **after an additional restart for
  provider configuration** after 3 probes.

For future code updates, use
`scripts/ops/sync_tender_agent_runtime.sh` from the Data Platform
repo. It mirrors the canonical Tender checkout into internal APFS
without auto-restarting the service or overwriting the existing
private runtime config; restart with `launchctl kickstart -k` in
an approved maintenance window and check health. Do not directly
switch the launchd program back to the original SSD path.

## Actual public procurement E2E

The live public EIS search from 2026-10-06 to 2026-10-09 succeeded
after the internal runtime and public `demo_data` supplier profile
were correctly installed. The buyer's real public purchase
**0372200172326000015**, website of the St Petersburg Bread Museum,
was processed:

- one public EIS search page, one actionable search result;
- six procurement source attachments fetched;
- contract/requirements/economics evidence processed;
- an HTML report generated locally in 4.375 s;
- `completed_with_warnings` and `manual_review_required`, with
  insufficient source-grounded supplier price evidence flagged;
- no application submitted, no digital signature, no external
  emails or messages sent.

This first production run used the **deterministic fallback**:
the former backend default was `AI_CORP_LLM_PROVIDER=stub`.
Do not relabel this specific report as LLM-supported.
Output is under
`/Volumes/ArvectumSSD/Arvectum/runtime/model-profile-tender-acceptance-20261009/`,
including the HTML report and `_evidence.md`.

## Local Gemma validated

A **separate controlled LLM run** used only accepted public
procurement test fixtures plus an expressly labelled synthetic
contract snippet; no real supplier TKPs were invented. Its
trace/workspace database was isolated to a QA SQLite database
and the provider sent requests solely to local Gemma
`:8081/v1/chat/completions` with JSON schema requirements.
After ~146 s the complete controlled Tender Operator Pilot succeeded:

- `analysis_mode=llm_tender_operator_provider`;
- `resolved_provider=openai_compatible`;
- validated requirements, supplier questions, RFQ draft, contract
  risk memo, redacted partner-export content, review checklist,
  operator decision form, feedback and outcome;
- status `rfq_ready_collect_tkp`. No real supplier proposals exist,
  so downstream real-world price/margin/GO decisions remain under
  an explicit human gate.
- no external partner delivery was performed; the test's
  `delivered_manually` flag belongs to a synthetic local workspace
  exercise, not a sent communication.

The production PostgreSQL URL was tested without printing it;
SELECT 1 passed and `Base.metadata.create_all` in a rollback-only
transaction passed. Controlled provider settings were then enabled
in the internal private runtime env:
`AI_CORP_LLM_PROVIDER=openai_compatible`,
`AI_CORP_LLM_MODEL=arvectum-gemma4-12b-it-qat-q4_0`,
`AI_CORP_OPENAI_BASE_URL=http://127.0.0.1:8081/v1`,
120s timeout, one attempt and a local dummy API-key header required
by the SDK (no external LLM provider). Only localhost communication
is authorized. Original private environment backed up as
`runtime.env.bak-20261009-before-local-llm`.

**Important remaining gate:** A fresh public EIS procurement run
through the **production** backend using this newly configured
LLM provider was attempted but blocked by remote-execution security.
Therefore **no production EIS-to-LLM end-to-end score can be claimed**
yet. The earlier live EIS-to-report and the separate validated local
Gemma workflow are two distinct, completed checks, not a proof of
their combined success.

## Operator checks

```bash
# Read-only:
curl -fsS http://127.0.0.1:8001/health
curl -fsS http://127.0.0.1:8094/health
curl -fsS http://127.0.0.1:8081/health

# Controlled restart verification:
launchctl kickstart -k gui/$(id -u)/com.arvectum.backend
curl -fsS http://127.0.0.1:8001/health
```

**24/7 default** remains the Gemma `quality` profile because
persistent Arvectum OS may call the model name on `:8081`.
The Qwen3.5 4B `fast` profile is fully deployed and reversible but
requires `--acknowledge-shared-consumers`; while active, existing
Gemma-specific consumers may degrade. Do not keep both large LLMs
resident on the 24 GiB Mac mini.
