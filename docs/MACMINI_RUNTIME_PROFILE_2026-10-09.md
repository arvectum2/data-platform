# Mac mini: runtime profiling and Data Platform + Tender Agent integration (2026-10-09)

**Hardware:** Apple Silicon, 24 GiB unified memory. **Priority:** make an effective, reversible Mac-only test stack before later GPU VPS migration. **Status:** acceptance testing substantially complete, **NOT safe to finalize production switch until macOS external-SSD file-open access is restored**.

## What was actually performed

1. Shut down booted **iPhone 17 iOS 26.5 Simulator** using `xcrun simctl shutdown all` and quit Xcode. Confirmed no booted simulators remain. Did **not** remove Xcode installations or interrupt essential launchd jobs.
2. Kept Docker Desktop and all five required containers online: `arvectum-postgres`, `arvectum-local-e2e-db-1`, `arvectum-local-e2e-redis-1`, `arvectum-local-e2e-worker-1`, `arvectum-local-e2e-api-1`.
3. Verified Data Platform `:8094`, Tender Agent backend `:8001`, embeddings `:8090`, reranker `:8091`, initial Gemma `:8081`. Confirmed from authenticated runtime config (without exposing credentials) that production uses Qwen3-Embedding-4B Q8 2560d, BGE reranker top 3, Tesseract rus+eng at 220 DPI, Gemma 4 12B QAT Q4, vision currently disabled and `ARVECTUM_DATA_MODEL_MAX_CONCURRENCY=1`.
4. Ran a real authenticated **Data Platform API + PostgreSQL E2E** in a uniquely named **ephemeral test collection** with public Russian procurement native PDF, DOCX and scanned PDF. Indexed **3 documents / 14 chunks / 14 embeddings**; checked two live hybrid reranked queries, generated the correct legal-entity name and OKUD code with two cited claims, and verified the test collection was deleted. No existing customer collection was modified.
5. Ran **43/43** Tender Agent Data Platform consumer/auth/recovery/document tests; live `arvectum_data_client.DataPlatformHttpClient` against an existing tender collection returned 5 hits in **0.395s**, read-only. This validates the cross-product retrieval boundary, **not** a full autonomous Tender Agent S1-S7 process.
6. Brought up Qwen3.5-4B MLX 4bit in an isolated OpenAI-compatible local HTTP server (`:18081`), passed **7/7** simple and two longer public-document checks with exact amounts, entity names and grounded abstention (mean **3.975s**, two long questions **11.458s** and **10.879s**). Full API compatibility verified through an independently launched temporary DP API `:18094`, without altering launchd production settings.
7. Qwen3.5-9B co-resident stress with Gemma/embedding/reranker/Docker triggered excessive swap/memory pressure and was halted. **No valid 9B same-load E2E score**.
8. Ran a **controlled single-LLM trial**. The shell script temporarily booted out the original Gemma launchd job, ran the same live API E2E against the temporary Qwen4 DP, and bootstrapped the original Gemma job back automatically on exit.
9. Shut down the temporary Qwen MLX and temporary DP API services after the tests.

## Controlled A/B/C live E2E measurements

All three tests used the same three public Russian procurement fixtures, actual `/v1/ingest/document`, persistent PostgreSQL indexing, `/v1/search` + BGE, `/v1/answer`, source checks, and verified test-collection deletion. These are **one-shot wall-times under different memory conditions, not statistical p95 SLA**.

| Configuration | Answer stage | DOCX ingestion | Total wall-time | All semantic/cleanup checks |
|---|---:|---:|---:|---|
| Production Gemma 4 12B at :8081; Qwen4 embed, BGE, Docker | **58.280s** | 19.727s | 84.833s | PASS |
| Experimental Qwen3.5-4B at :18081 **co-resident** with Gemma; independent API :18094 | **37.497s** | 19.666s | 64.092s | PASS |
| **Qwen3.5-4B as the only loaded LLM**, production Gemma launchd temporarily paused | **13.471s** | 19.672s | **41.129s** | PASS |

During the bounded Gemma pause, macOS `memory_pressure` free percentage grew from roughly **11% to 44%** and allocated swap dropped from ~24 GiB to ~13.9 GiB. Stopping the temporarily co-resident 9B also improved memory pressure. **Do not run Gemma 12B and Qwen3.5 4/9B simultaneously as persistent servers on this 24 GiB machine**.

The Mac initially had ~22 GiB used swap despite shutting down Simulator. Docker exposes about 8 GiB RAM; the five containers' `docker stats` accounted for only ~440 MiB of container memory. A reasonable post-permission optimization is to configure Docker Desktop for **4–5 GiB VM RAM** (after validation/restart), not to shut down the PostgreSQL stack. Docker Desktop's settings file is blocked by macOS TCC for RDC, so **no Docker RAM setting was modified**.

## Recommended Mac mini configuration

### Fast E2E test profile (target, **not yet promoted**)

- Native source PDF/DOCX/XLSX readers; **Tesseract rus+eng** default scanned page OCR.
- Optional single-page **Qwen3-VL-4B MLX 4-bit** from a separate non-resident / lazy-on-demand OCR worker. Limit to one expensive GPU job at a time, unload model after use; QA gold CER **4.54%** on only two human-reviewed Russian scans. 8B VLM for manual high-assurance batch only, not resident.
- **Qwen3-Embedding-4B Q8** `llama.cpp` `:8090`, `2560d` permanent. Existing production pgvector indexes are built at 2560d; do NOT mix with Giga 2048d.
- **PostgreSQL hybrid FTS + pgvector + RRF** via Data Platform `:8094`.
- **BGE-reranker-v2-m3** sidecar `:8091` (cross encoder top-3 default, fail-open).
- **Qwen3.5-4B MLX 4bit** as the *exclusive resident* local answer LLM (temporary OpenAI-compatible `:18081` was validated). Use local-only localhost binding, concurrency 1, `enable_thinking=false`, bounded prompt KV cache, max accepted length with deterministic source citations. Cross-product API contracts stay unchanged.
- Keep **Gemma 4 12B Q4 as a selectable quality profile** for difficult legal procurement decisions; do not run it concurrently with the Qwen4 test profile on 24 GiB. This requires an explicit provider-profile/launchd handoff with rollback and an audit of other consumers of Gemma `:8081`, especially Arvectum OS; do not silently make this switch.
- Docker PostgreSQL remains on and Tender Agent backend remains reachable. Model scaling and GPU queueing are separate from data volume and search index management.

### Current production profile, until SSD permission recovers

- Same Qwen3-Embedding-4B, BGE, Tesseract, hybrid index, DP and Tender backend.
- Gemma launchd job remains configured and registered, but **its new process has been stuck at `Loading model` / HTTP 503 since the controlled restart**. Other DP/search/Tender health endpoints returned 200.
- Do **not** claim the entire reasoning pipeline healthy at this moment. Its external model path is `$HOME/.ollama/models/blobs/...gguf`, symlinked to ArvectumSSD. The Mac's `tccd` began re-authorizing Node 26.11 and actual `open()` calls on files from ArvectumSSD started blocking. Even a small manifest read from RDC stalled; attempts to copy/hyperhash the GGUF file were cancelled when disk open failed to advance.
- RDC was shut down and launchd restarted it to retrigger the macOS Removable Volumes permission prompt. **User needs to approve the macOS prompt.** Do not unmount the SSD or restart the Mac/Docker on this evidence alone.

## Required safe recovery and rollout gates

1. **Access first:** on Mac mini approve macOS privacy request for updated RDC Node and removable ArvectumSSD. Verify that a fresh process can `open()` and read a small SSD file promptly, not just `stat()` it. Check both the remote shell and launchd process identity. Avoid repeatedly retrying a blocked 7+ GiB model load.
2. Verify original Gemma `:8081/health` becomes HTTP 200, with actual successful generation. If not, safely restart after fixing file authorization, using the existing launchd plist and baseline files; do not destroy the model cache.
3. Copy **only** high-value essential GGUF launchd weights (Gemma and possibly Qwen embeddings) to an internal runtime directory **after byte count and SHA-256 match**, where launchd startup does not depend on External Volumes TCC after Node updates. User volume has >100 GiB free, but don't duplicate needlessly. Preserve external SSD as model archive.
4. Document a reversible exclusive `quality=Gemma` / `fast=Qwen3.5-4B` model router profile with a preflight test of consumers bound to Gemma `:8081`; don't disable other always-on launchd services.
5. Only after successful profile handoff, benchmark full Tender Agent retrieval + bounded S1..S7 business flow on *public/non-sensitive* procurement data, and record per-stage p50/p95, source fidelity, exact numbers and memory/queue. At present the live Tender retrieval SDK and related 43 tests passed, but full S1..S7 was not executed here.
6. Validate real **Qwen-VLM OCR escalation through Data Platform**, not merely the standalone MLX runner, plus document page/table provenance; archive golden fixtures.
7. Optionally reduce Docker Desktop memory allocation from about 8 GiB to 4–5 GiB **only via supported Docker UI and after container restart/recovery checks**. Keep all five required containers.
8. For VPS, keep pluggable OpenAI-compatible LLM and OCR interfaces; MLX on Mac, CUDA-compatible inference on GPU VPS. Linux CPU VPS alone is not a performance replacement for Mac Metal.

## Artifacts

Local smoke scripts were authored in the canonical DP repo on ArvectumSSD but **cannot be Git pushed while SSD file operations stall**:

- `scripts/ops/smoke_live_macmini_tender_dp.py`: unique temporary collection, ingest/search/answer and verified deletion
- `scripts/ops/bench_macmini_single_llm.sh`: controlled Gemma launchd pause/restart with restore trap
- `scripts/benchmark_qwen35_4b_http_macmini.py`: 7-case Qwen 4B/9B long-context exploration

Machine-readable outputs on SSD:
`/Volumes/ArvectumSSD/Models/data-platform-benchmarks/quality-results/macmini-live-e2e.json`,
`macmini-live-e2e-qwen35-4b.json`,
`macmini-live-e2e-qwen35-4b-single-llm.json`,
`qwen35-4b-http-real-context.json`, and `tender-dp-sdk-live.json`.
Do not mistake saved files for verified GitHub files until access is restored.

**Operational verdict:** For Mac mini 24GB, the best-tested *fast* model profile is Qwen3-Embedding-4B + BGE + Qwen3.5-4B MLX exclusive + Tesseract (+ Qwen3-VL-4B on demand); retain Gemma as a mutually exclusive higher-assurance profile. Further model replacement is secondary to fixing SSD permissions and completing sustained cross-product E2E.

## Post-approval recovery — 2026-10-09 12:13 MSK

**The previously reported SSD permissions blocker is resolved.** Following
user approval, new remote processes read the model manifest, repo roadmap
and the first bytes of Gemma GGUF from ArvectumSSD in ~0.001 seconds each.

Gemma weights are now also stored at
`/Users/master/arvectum-runtime/models/gemma4-12b-qat-q4.gguf` on
the internal APFS volume, with 7,381,382,048 bytes and an SHA-256
checksum matching the original immutable Ollama blob
`1278394b693672ac2799eadc9a83fd98259a6a88a40acfb1dcaa6c6fc895a606`.
Original weights on SSD were not deleted.

The original `ssd-gate.sh` was backed up as
`ssd-gate.sh.bak-20261009-internal-gemma`, and the `llama-8081`
model path was changed to the verified internal copy, without altering
the host port, model alias, or other SSD-gate cases. The original
launchd job was restarted and healthy in eight probe attempts.
Gemma served an actual HTTP 200 chat completion preserving `0506135`
in 1.116 seconds.

At the final check, Gemma :8081, Qwen embeddings :8090, BGE :8091,
Data Platform :8094 and Tender Agent :8001 returned 200.
The two test-only servers were stopped, and iOS Simulator remains
shut down. A point-in-time memory_pressure free percentage was 26%.

**Important:** production Data Platform still uses Gemma as its LLM.
Qwen3.5-4B MLX has only been validated as an exclusive fast-profile
candidate through a temporary, isolated API. A permanent switch must
account for other consumers of :8081 and include a rollback path.
The SSD gate still verifies the presence and symlinks of the external
volume before launching Gemma; only the weight file was moved to an
internal verified copy. This is not a guarantee of startup without SSD.
