# Isolated Qwen3-Embedding-4B staging admission — 22 Nov 2026

**Scope:** Data Platform issue #133, draft PR #134, Tender Agent Core runtime release gate. A separate Qwen3-Embedding-4B benchmark can be run only after independently verified spare host resources. Running release on localhost:8094 and live model on localhost:8090 must be untouched. **This report is a resource safety preflight, not a completed Qwen performance benchmark.**

## Actual read-only preflight

Mac mini M4 Pro, 24 GiB unified RAM, 12 logical CPUs. Live resource governor: `status=pass` but `mode=reduced`, with memory free approximately **34%**, memory-pressure level **2** and reason `memory_pressure`. macOS `vm.swapusage` observed **>6 GiB** in use. Running Qwen3-Embedding-4B Q8 GGUF occupies a separate existing llama.cpp process. An otherwise available model file at its original read-only path has stat size **4,279,660,224 bytes**; size alone is not a content-authenticity checksum.

A read-only MacBook Air offload check found 16 GiB RAM, >6 GiB swap in use and **no local Qwen GGUF or llama-server binary**; transferring or loading the model there is not a justified low-risk shortcut.

On real Mac mini, `python scripts/ingest_slo_qwen_stage_gate.py --check-only` returned `blocked`, exit code **2**, with exactly four reasons:

- `governor_not_normal`
- `memory_headroom_low`
- `memory_pressure_high_or_unknown`
- `swap_used_too_high_or_unknown`

**No second Qwen process was launched**, no live inference requests were sent, and no settings or production services were changed. The guard was also exercised via the stage runner's dry-run; it remained blocked.

## Versioned safe preparation in PR #134

- `scripts/ingest_slo_qwen_stage_gate.py`: strict-only admission requires fresh governor mode `normal`, >=50% free host RAM, pressure0, CPU<=50%, GPU<=60%, thermal0, disk>=20GiB, swap used<=2048MiB, expected GGUF file size, executable server, unused **stage** port and matching Apple ARM host. Missing/stale data blocks. A future independent process will need runtime monitoring; the gate does not itself start anything.
- `scripts/ingest_slo_qwen_stage_run.py`: executable **synthetic-only** CPU-stage harness, with a **separate** loopback endpoint `127.0.0.1:18190` vs live `8090`, no API keys or DB, original model file opened read-only by llama.cpp, `--n-gpu-layers 0`, 2 CPU threads, one server slot, ctx4096 and a strict maximum runtime 420 seconds. Default is dry-run. Explicit `--execute` only runs after all fail-closed admission conditions pass.
- Two distinct generated synthetic chunk sizes (128 and 512 characters, 8 distinct chunks per request); concurrency1/4, 20 attempts per cell, 80 planned requests in randomized repeated four-request blocks, two initial warmups, per-request timeout45s; no retries or unbounded resubmission. Aggregate report contains only numeric latency, counts and local model alias; vectors, synthetic prompts and source IDs are never saved.
- During the test, a separate resource monitor checks admission regularly, ignoring only the expected occupation of the dedicated stage port; if any host condition is no longer safe the run aborts, queued work is cancelled, and the temporary server is terminated. Process stderr/stdout discarded. No new permanent launcher, schedule, DB or auth.
- Local source-focused pytest **37 PASS** and Ruff PASS at code head `aca952e3174df5125cc12e628bdc89dd19d1b94a`, including a mocked 8-vector Qwen JSON response, malformed response rejection and blocked-admission no-launch test. This is synthetic harness acceptance only, **not actual model performance**.

### Reproducible commands (when capacity is restored)

Read-only preflight:

```sh
python scripts/ingest_slo_qwen_stage_gate.py --check-only
python scripts/ingest_slo_qwen_stage_run.py
```

**Do not** run the next command while preflight returns blocked. Actual isolated Qwen stage, only after independent approval that its resource envelope is safe:

```sh
python scripts/ingest_slo_qwen_stage_run.py --execute
```

The runner is deliberately an isolated **CPU-only control**, not equivalent to the deployed Qwen GPU-offloaded model. Even a completed CPU P95 must not be compared directly to production ingest latency and cannot establish the actual queue wait independently of model inference. The aggregate `queue_latency_separately_measured=false` records that boundary.

## Technical findings and next decision

Read-only live process mapping previously verified Data Platform uses `llama_cpp` Qwen3-Embedding-4B at `8090/v1`, inference batch size8. The live llama-server is configured with a single parallel slot. The software pipeline keeps an open SQL session during embedding, so database transaction contention is a separate **possible** problem; no independent causal measurements justify changing this yet.

After this resource gate is green, the next safe stage is a bounded *isolated* model sample with actual timing and server-side queue/inference telemetry if exposed. If the model stage cannot reproduce the actual bottleneck, add an instrumented synthetic-only full-pipeline experiment with controlled embedding backend and PostgreSQL, not live source data. **Do not optimize or change production under unverified assumptions.**

Production recorded an ingest P95 of **20,152ms** / 256 recent samples (target 10,000ms) from an authorized GET on 22 Nov, with 8,032 cumulative requests and 0 recorded cumulative errors. The SLO remains RED. Keep Tender Agent Core/PRICE runtime release **BLOCKED** until representative sustained real SLO passes, independent source-grounded Gemma acceptance, owner approval and rollback proof.
