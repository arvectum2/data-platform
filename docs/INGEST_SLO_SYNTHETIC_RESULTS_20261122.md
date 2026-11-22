# Data Platform ingest — isolated synthetic staging proof (2026-11-22)

**Scope:** narrowly scoped continuation of Data Platform issue #133 / Tender Agent Core release gate. No prod HTTP ingest, real source downloads, DB writes, source reindexing, production-model inference, backup retirement, or deploy.

## Actual experiment

Two disposable executions on Mac mini (macOS, M4 Pro; 2026-11-22 ~16:11–16:12 UTC) used a **separate fresh Docker `pgvector/pgvector:pg17` database**, bound only to `127.0.0.1:55435`, with container caps **768 MiB RAM, 1 CPU**. Execution was single-use, Docker was removed on exit and cloned source was removed. The generator rejects the production DATABASE_URL environment and hardcodes the disposable test identity/port; no actual original source records or customer documents were submitted. Numeric trace contained no text or source identifiers and was deleted after checking its SHA.

Pinned embedding: `hashing:local-hash-v1:64` (deterministic **synthetic-only** baseline). This is **not** the running production embedding model, and it cannot certify production ingest SLO.

- Original generator HEAD `8fcb82b57186e04c4f7c9e994f9600d9785a9817`: 80/80 complete, 0 errors, 0 retries, total P95 **31 ms**, max **46 ms**; trace SHA-256 `4e80d6df872dcf345043a1bfbb51ae3fb10880491142da356e754a5ee1a72373`. **This result has a known analyzer grouping defect:** input sizes 8 and 64 KiB were combined into one bucket, so size-specific claims from this run are invalid.
- Corrected analyzer HEAD `5f274c542674f32502db21a0a5178dc6472c2c6c`: 80/80 complete, 0 errors, 0 retries, total P95 **33 ms**, max **50 ms**, trace SHA-256 `23582d3f6cd995214ccb4e32afa151d242eda761ca81d4e60dae430d243d708b`. SHA is for the **deleted numeric-only trace**, not a customer document. Verified separate P95 cells (20 measurements each):

| Generated TXT size | Configured executor concurrency | Samples | P95 elapsed | P95 non-embedding persist/ORM* | Errors |
|---|---:|---:|---:|---:|---:|
| 8 KiB | 1 | 20 | 28 ms | 21 ms | 0 |
| 8 KiB | 4 | 20 | 50 ms | 41 ms | 0 |
| 64 KiB | 1 | 20 | 15 ms | 12 ms | 0 |
| 64 KiB | 4 | 20 | 33 ms | 24 ms | 0 |

*The diagnostic script measures `db_ms` as elapsed `_persist_and_index` minus measured provider inference. This includes Python/ORM and transaction overhead, **not pure SQL**. `chunk_ms` includes temporary-file and pipeline overhead as well as splitting. Phase P95 values need not sum to overall P95 (different observations).

**Cold-start/order caveat:** all 8 KiB cases ran before the 64 KiB cases, with no randomized interleaving. The apparent smaller-file disadvantage is **not** evidence that larger inputs are faster. Configured concurrency is executor capacity, not observed simultaneous active request count. The experiment is isolated **direct ingestion**, not an HTTP upload latency test.

## Why this does not fix the production defect

The prior authorized **read-only production metadata** showed `/v1/support/readiness` ingest P95 **18,887 ms / 256 last samples**, target **10,000 ms**, and 0 cumulative errors / 7,989 requests. This synthetic hashing benchmark cannot reproduce the actual document mix, deployed embedding model, runtime concurrency, model load, or endpoint request timing.

Independent **read-only process observation** on Mac mini found a live llama.cpp embedding server with **Qwen3-Embedding-4B**, 8192 context, `--parallel 1`, on loopback port 8090. **Whether the active Data Platform actually uses that exact server/configuration for these samples is not yet independently attested.** No inference or real document requests were sent to it.

Therefore the stage confirms correct isolation, numeric evidence integrity and a **fast synthetic hashing control only**. The real root cause of 18.9s production ingest is **unknown**. Do not modify production code to optimize an unverified causal hypothesis.

## Follow-up and release gating

1. Ground the active DP embedding provider/model and model call batching/attempts in read-only authorized runtime configuration or source-safe status, without logging credentials, document payloads or collection identifiers.
2. On a separately authorized isolated staging model (not the live inference service), warm up the pipeline, randomize/counterbalance size order, reproduce production-representative synthetic document/chunk distribution, and instrument separate decode/chunk/provider/wait/retry/transaction spans without log leakage.
3. Crosscheck source-safe live aggregated latency window with stage-level instrumentation; test whether model concurrency `1`, queue/wait, retries, and batch sizes contribute. If a bottleneck is **actually observed**, prepare bounded source- and tenant-safe change with negative tests.
4. Validate **sustained representative** ingest P95 <= 10,000 ms, <= 1% errors over >=20 measurements, and independently verify real Gemma/source qualification; production Core/PRICE release requires exact owner authorization and rollback.

**No auto deployment; no SLO relaxation; no claim of root cause fixed.** Review PR #134 retains the scoped persistent checkpoint.
