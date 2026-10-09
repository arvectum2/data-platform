# Mac mini exclusive LLM profiles (24 GiB) — deployed 2026-10-09

## Intended behavior

Both LLM configurations use the **same existing launchd job**
`local.llama-server-8081`, bound only to `127.0.0.1:8081`.
There is **never a concurrently resident second answering LLM**.
Embedding `:8090`, BGE reranker `:8091`, Data Platform `:8094`,
Tender Agent `:8001`, and the Docker/PostgreSQL stack remain unchanged.

The boot-time selector `macmini_llm_launch.sh` chooses the implementation
from `/Users/master/arvectum-runtime/data-platform/.llm-profile`.
If that file is missing, the safe default is `quality`.
The existing SSD mount/symlink gate remains intact. Models are read
from **internal APFS**, not from the Hugging Face SSD cache:

| Profile | Model | Format / runtime | Model path | Context / maximum |
|---|---|---|---|---|
| `quality` | Gemma 4 12B | QAT Q4 GGUF, llama.cpp | `/Users/master/arvectum-runtime/models/gemma4-12b-qat-q4.gguf` | 32768 tokens, single slot |
| `fast` | Qwen3.5 4B | MLX 4bit, `mlx_lm.server` | `/Users/master/arvectum-runtime/models/qwen3.5-4b-mlx-4bit` | one active decoding request, bounded cache and 640-token default output |

The original Gemma blob (7,381,382,048 B) and internal copy have the
same SHA-256 `1278394b693672ac2799eadc9a83fd98259a6a88a40acfb1dcaa6c6fc895a606`.
The Qwen 4B internal copy includes `model.safetensors`, tokenizer
and configuration; source and destination SHA-256 for all three were
independently checked. The Qwen model is ~3.03 GB of safetensors.

## Operator commands

On Mac mini:

```bash
cd /Volumes/ArvectumSSD/Arvectum/repos/data-platform
python3 scripts/ops/macmini_llm_profile.py status
python3 scripts/ops/macmini_llm_profile.py fast --acknowledge-shared-consumers
python3 scripts/ops/macmini_llm_profile.py quality
```

**Important shared-service constraint:** Arvectum OS's persistent
`launchd` job can also consume Gemma's former `:8081` model name.
The profile controller **requires an explicit acknowledgement** before
switching to `fast`. The Arvectum OS process stays running but requests
made while fast mode is active may not work with its Gemma-specific model
alias. **Keep `quality` as the 24/7 default until the Arvectum OS
consumer receives a model-agnostic provider interface and separate
acceptance testing.** Fast mode is safe for *bounded* Data Platform and
Tender Agent QA windows, not automatically an invisible drop-in for every
existing service.

A successful switch:
1. Obtains an exclusive advisory lock, validates both model directories.
2. Atomically writes the profile file and updates only DP's
   `ARVECTUM_DATA_REASONING_MODEL`, `REASONING_MODEL_VERSION`,
   `REASONING_BASE_URL` (same local port), and concurrency setting.
   Other secrets, PostgreSQL configuration and embedding dimension are
   preserved exactly; no secrets are printed.
3. Restarts the sole existing LLM launchd job.
4. Requires a **real completion** returning the expected Russian phrase.
5. Restarts Data Platform to load the new model identity, and checks
   `:8094/health`.
6. On timeout or error, restores original profile and environment,
   restarts the original LLM and Data Platform and verifies readiness.

This is a **brief planned inference interruption during switching**;
the data plane and underlying PostgreSQL remain online. Only one
operator may switch at a time.

## Acceptance run evidence

- Four unit checks for profile selection, atomic local config and
  preservation of unrelated settings: **4 passed**.
- Existing `quality` launchd restarted successfully under selector
  (HTTP 200 on `:8081` after 5 probe attempts).
- The first `quality → fast` attempt using SSD-backed Qwen weights
  timed out. The script automatically logged `ROLLBACK_OK`;
  Gemma and Data Platform were restored without modifying indexes.
- After copying/checksumming Qwen weights to internal APFS, the same
  `quality → fast` completed in **4.21 s**, with a verified actual
  completion after **2.692 s**.
- With `fast` on the real production DP API `:8094` (no temporary API
  server), an isolated public procurement 3-file E2E checked native
  PDF/DOCX/scanned PDF, PostgreSQL indexing, 2 hybrid reranked queries,
  exact source answer and verified test-collection deletion:
  **all checks passed**, answer stage **12.344 s**, total **46.604 s**.
- `fast → quality` completed in **14.24 s**, actual inference probe
  **12.587 s**, and all five `:8081`, `:8090`, `:8091`, `:8094`,
  `:8001` services returned HTTP 200.

Raw machine-readable API test lives under the SSD
`quality-results/macmini-live-e2e-fast-profile-permanent-api.json`.
Public-source test collection was deleted; no customer records were touched.

## Recovery

The previous `ssd-gate.sh` is preserved as
`/Users/master/arvectum-ops/arv-075/scripts/ssd-gate.sh.bak-20261009-profiles`.
The installed profile selector is
`/Users/master/arvectum-runtime/data-platform/macmini_llm_launch.sh`.
To recover without using the selector, restore the backup gate script,
restore the original production runtime environment where appropriate,
and use the existing launchd job rather than installing a duplicate
resident LLM. A standard `quality` switch should be tried first.

## Remaining acceptance boundary

The **full autonomous Tender Agent S1..S7 on a real procurement**, including
document acquisition, supplier and price evidence, legal review and all
human approval gates, is distinct from the proven shared DP ingestion →
search → answer smoke. Do not mark it passed solely because the base
pipeline, stub workflow, 43 boundary tests, and live Tender SDK retrieval
are passing. The canonical public-EIS runner may stop safely if the
search backend requires authorization, published notices are not found,
or source attachments cannot be retrieved. Record its actual result
before claiming this gate.
