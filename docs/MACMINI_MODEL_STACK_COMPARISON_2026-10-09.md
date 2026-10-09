# Data Platform — consolidated model benchmark and Mac mini E2E target stack

Date: **2026-10-09**, hardware: **Apple Silicon Mac mini, 24 GiB unified memory**, ArvectumSSD.
Environment: three existing production model processes plus Data Platform API,
other user applications, Docker and an iOS Simulator. **All benchmark runs kept
production model choices, endpoint configuration, indexes and stored vectors unchanged.**

## Decision

For bounded 24 GiB end-to-end testing:

| Pipeline layer | Choice | Why |
|---|---|---|
| Native PDF / DOCX / XLSX | Deterministic format-aware parser, tables + row/cell source references | Do not force VLM into born-digital files |
| OCR fast default | **Tesseract rus+eng**, deterministic quality/field validator | ~0.83 s/page on two accepted scans; predictable and cheap |
| OCR escalation | **Qwen3-VL-4B-Instruct MLX 4bit** | Two-scan CER **4.54%**, ~**17.1 s/page**; usable on Mac, much better than this GGUF runner |
| OCR high-stakes manual escalation | Qwen3-VL-8B MLX 4bit, lazy and exclusive | Two-scan CER **2.83%**, ~**27.1 s/page**; quality gain but latency and memory overhead |
| Embeddings | **Qwen3-Embedding-4B Q8 GGUF**, llama.cpp, dimension 2560 | Top-1 **66.7%**, MRR **0.785** on 45-site-page/12-RU-query smoke, already indexed in production |
| Alternate embedding experiment | **Giga-Embeddings 0826 3B BF16**, dim 2048 | Recall@5 **100%**, nDCG@5 **0.806**, vs Qwen4B 91.7%, 0.808; requires *new isolated* vector index |
| Fast embedding option | Giga-Embeddings 0826 480M, dim 1024 | 4.58 s for 45 pages/12 queries, but Top-1 50%; avoid promoting without a larger corpus |
| Retrieval | PostgreSQL FTS + pgvector + RRF + metadata and evidence/provenance | Existing production hybrid retrieval; pure dense smoke is NOT an end-to-end search benchmark |
| Reranker | **BGE-reranker-v2-m3**, sidecar, top-3 by default | In fixed top-five smoke nDCG@5 **0.813**, p50 **0.279 s**; efficient with fallback on outage |
| LLM grounded answers | **Gemma 4 12B QAT Q4**, llama.cpp | 5/5 strict lexical/citation/abstention smoke, accepted current baseline |
| Fast LLM candidate | **Qwen3.5-4B MLX 4bit** (separate optional adapter) | Same simple five cases 5/5, 0.93 s mean; no proven equivalence on hard RU legal reasoning |
| Application/service | Existing Data Platform :8094, SDK/API, PostgreSQL/pgvector, Ollama-independent headless GGUF server and dedicated Python sidecars | Keeps transport stable; allows provider/runtime swap without touching schemas |

**Memory policy:** keep existing baseline resident and at most one extra VLM
or heavyweight benchmark active. Use an explicit GPU/unified-memory budget,
per-service concurrency=1 for expensive workloads, OCR escalation queue,
idle unload, backpressure and application memory telemetry. **Never run
the 20.95 GB BF16 MoE checkpoint alongside production on 24 GiB memory.**
The Mac is a development/proof-of-integration stand, not a guarantee that
all models can be served concurrently at production latency.

## Local inventory coverage: 23/23 accounted for

18 previously staged variants + five ai-sage Russian variants, all fully
downloaded, their on-disk file integrity verified before this study.
**19/23 variants have quality-smoke results** either from initial October 9
work or today's expanded runs. Four have explicit bounded feasibility
deferrals. Different versions and serving formats are counted separately
because model behavior and speed can differ.

### Embeddings (same 45 actual Arvectum Site HTML documents, 12 frozen RU queries)

| Model | Emb dim | Top-1 | MRR | Recall@5 | nDCG@5 | Encode 45 docs + 12 queries |
|---|---:|---:|---:|---:|---:|---:|
| Qwen3 Embedding 0.6B GGUF Q8 | 1024 | 58.3% | 0.726 | 83.3% | 0.741 | 6.37 s |
| **Qwen3 Embedding 4B GGUF Q8** | 2560 | **66.7%** | **0.785** | 91.7% | **0.808** | 35.50 s |
| Qwen3 Embedding 8B GGUF Q4 | 4096 | 58.3% | 0.732 | **100%** | 0.798 | 71.39 s |
| BGE-M3 BF16 (dense-only, MPS) | 1024 | 50.0% | 0.675 | 83.3% | 0.699 | **3.51 s** |
| Giga Embeddings 480M BF16 (MPS) | 1024 | 50.0% | 0.711 | **100%** | 0.784 | 4.58 s |
| **Giga Embeddings 3B 0826 BF16 (MPS)** | 2048 | 58.3% | 0.742 | **100%** | 0.806 | 19.89 s |

**Not quality-scored, but downloaded:**
- `ai-sage/Giga-Embeddings-instruct` (2025 legacy): **13.80 GB float32**
  weights. Running the original precision concurrently with production on 24 GiB
  was rejected by the memory gate; the model needs separately evaluated
  FP16/quantized local serving before meaningful comparison.
- `ai-sage/Giga-Embeddings-instruct-10B-A1.8B-0826`: **20.95 GB BF16**
  weights (MoE, 1.8B active but ~10B resident total). This checkpoint
  cannot be a default Mac-only 24 GiB end-to-end runtime alongside
  production; keep archived for quantization / higher-RAM-GPU VPS.

BGE-M3's sparse and multi-vector outputs were NOT benchmarked, only its dense
SentenceTransformer pathway. Do not conclude that all BGE-M3 hybrid
capabilities are inferior. Qwen GGUF backends differ from Giga/BGE Torch
Metal; absolute encode times are **not apples-to-apples model-only throughput**.
Giga models used model-prescribed query instructions, prior Qwen baselines
used plain queries. Twelve search questions cannot establish significance.
These pages are the company website, *not 100+ labelled procurement contracts*.

### Rerankers (same Qwen3 4B dense top-five per query; 12 queries)

| Model/serving | Top-1 | MRR | nDCG@5 | p50/query, five docs |
|---|---:|---:|---:|---:|
| **BGE-reranker-v2-m3**, current sidecar | 66.7% | **0.778** | **0.813** | **0.279 s** |
| Qwen3 Reranker 0.6B CPU | 66.7% | 0.746 | 0.787 | 7.588 s |
| Qwen3 Reranker 0.6B MPS BF16 | 66.7% | 0.746 | 0.787 | 0.463 s |
| Qwen3 Reranker 4B MPS BF16 | 66.7% | 0.764 | 0.803 | 2.577 s |

The Qwen3-Reranker-4B initially **hit Metal OOM** at a deliberately imposed
0.42 allocation fraction (~7.46 GiB allowed). It completed with a more
permissive but still bounded 0.55 fraction and 16.81 s load time; quality
did not justify that memory cost and latency. Qwen 0.6B ran but lost to BGE.

### Document OCR and VLM (same TWO frozen, human-reviewed 2026 RU procurement scans)

| OCR pathway | Mean CER ↓ | Mean WER ↓ | Seconds/page | Required strings |
|---|---:|---:|---:|---:|
| Tesseract rus+eng | 21.40% | 29.75% | 0.83 s | 2/2 |
| Qwen2.5-VL-3B MLX 4bit | 9.36% | 20.85% | 15.11 s | 2/2 |
| Qwen2.5-VL-7B GGUF Q4 | 15.50% | 22.03% | 32.40 s | 2/2 |
| Qwen3-VL-4B GGUF Q4 | 15.45% | 22.93% | 19.45 s | 2/2 |
| **Qwen3-VL-4B MLX 4bit** | **4.54%** | **7.14%** | **17.06 s** | **2/2** |
| **Qwen3-VL-8B MLX 4bit** | **2.83%** | **6.56%** | **27.07 s** | **2/2** |
| PaddleOCR-VL-1.6 converted from original BF16 into MLX | 21.97% | 31.35% | 5.61 s | 1/2 |

**Specialized OCR not scored as full pipelines:**
- PaddleOCR-VL-1.6 **did run** through a converted BF16 MLX VLM on
  two pages, but the naive direct image-to-text call failed one mandatory
  text anchor. The official PaddleOCR document-parser also includes
  layout detection/cropping/merging. Our direct call does NOT represent
  its full quality; compare that on its official Apple Silicon pipeline
  before considering promotion.
- dots.ocr: original 6.08 GB weights converted to MLX BF16 and loaded,
  but inference was **terminated by the safety memory budget** when
  system memory reached ~23 GiB used, ~17 GiB wired, ~0.5 GiB unused
  (with prod/Docker/iOS simulator alive). No valid OCR score. Do not
  serve this unquantized variant persistently on this shared Mac.
- DeepSeek-OCR: staged 6.67 GB original weights, no verified production-safe
  Apple Silicon Metal adapter for its custom decoding architecture; not
  passed off as a benchmark. Prefer testing on CUDA VPS or obtaining a
  validated quantized/MLX-compatible conversion.

**CER is a normalized Levenshtein edit distance to two accepted
gold transcriptions**; outputs with changed layout/punctuation may be
penalized. Two pages are dramatically undersized for official adoption.
The same images and prompt intent were used, but GGUF/MLX model
quantization, image preprocessing, backend implementation and
output templates were different. Results demonstrate *this tested runtime
combination*, not universal superiority of MLX over GGUF.

### Grounded Russian answer synthesis (same FIVE frozen real-source cases)

| Candidate | Exact term check | Citation-ID check | Abstention | Mean latency |
|---|---:|---:|---:|---:|
| **Gemma 4 12B QAT Q4, current :8081** | **5/5** | 5/5 | 5/5 | 6.071 s |
| Qwen3.5 4B MLX 4bit | 5/5 | 5/5 | 5/5 | **0.925 s** |
| Qwen3.5 9B MLX 4bit | 5/5 | 5/5 | 5/5 | 1.555 s |
| GigaChat 3.1 Lightning Q4 GGUF | 3/5 | 5/5 | 5/5 | 0.930 s |

For Gemma, first request was 21.892 s and remaining four averaged
~2.116 s: cold/pre-warmed state substantially affects the mean. GigaChat
missed exact legal entity spelling (`Санкт- Петербурга` instead of
`Санкт-Петербурга`), not the identifier/amount checks. This evaluation
does NOT replace human-reviewed hallucination, context length and
contradiction tests on genuine large procurement documents.

## Minimal model-chain integration on Mac mini

A **read-only public-fixture smoke**:
native public 2026 procurement PDF, public DOCX table, and scanned
public procurement PDF (Tesseract) → local loopback
Qwen3-Embedding-4B :8090 (dense document search) → BGE :8091
(rerank) → Gemma :8081 (cited answer).
Results in `benchmarks/results/model_refresh_2026-10-09/macmini-model-chain.json`.

- Correct control-notice PDF retrieved at rank 1.
- Correct exact legal entity `Комитет финансов Санкт-Петербурга` and
  OKUD `0506135` present in model answer.
- Source references valid: model used a *comma-separated pair of source
  IDs inside one bracket*. First checker incorrectly expected one exact
  `[ID]` per bracket; saved raw answer was rescored with a corrected
  citation parser, yielding **4/4 passed**, without repeating inference.
- End-to-end **model-chain** wall time **34.57 s**, with extract 0.8,
  embedding 17.40, reranking 8.08, generation 8.29 seconds.
  This warm/cold/shared-load observation is NOT a reliable p95 SLA.
- **Not yet tested:** real Data Platform 8094 ingestion → pgvector writes
  → API hybrid retrieval → vector index revision lifecycle → ACL and
  provenance under concurrent OCR/LLM load. No production database
  records were changed in this test.
- Selected unit/integration suites for API/search/indexing/processing/
  documents/evaluation ran successfully, excluding postgres-marked
  tests; this is NOT the same as full persisted E2E.

## Memory and concurrency observations

During runs, the system also had Docker containers, at least one virtualized
device and iOS Simulator processes. Some heavyweight probes approached
24 GiB resident. After ending tests all four service health endpoints
:8090, :8081, :8091, :8094 answered 200, but memory pressure was still
high at the time of the last measurement; a robust local 24/7 design
must not assume idle-memory measurements from standalone model tests.
Do not disable MPS high-watermark safeguards; queue heavy VLM jobs and
limit active simultaneous model combinations. Observe unified RAM,
wired usage, swap, TTFT, p95 and process OOM on every sustained run.

## Architecture for Mac → VPS portability

1. Keep **Data Platform's ingestion/extraction/search/index/provenance
   contracts vendor-neutral**. Models are replaceable sidecars only.
2. Current GGUF/llama.cpp OpenAI-compatible `/v1/embeddings` and
   `/v1/chat/completions` contracts remain. Add a single local
   **MLX-VLM OCR adapter** behind a neutral `transcribe_page`
   internal interface, without changing the corpus schema.
3. OCR routing: native parser first; on actual image-only pages run fast
   Tesseract then heuristic checks for anchors, bad text quality,
   suspicious table structure and field integrity. Escalate only flagged
   pages to Qwen3-VL-4B. A separate high-assurance flag may route
   difficult pages to 8B under an exclusive GPU queue.
4. Store raw source, page numbering, box/row offsets, OCR provenance,
   model version, chunk hashes, and decisions; human adjudication for
   high-risk numbers/fields.
5. Treat embedding dimension as **immutable per index version**;
   comparing Giga 2048 and Qwen 2560 requires new side-by-side
   pgvector index collections, with no production vector overwrite.
6. VPS: PostgreSQL/object storage and application workers can live on
   RU-hosted CPU services, with separate appropriately sized GPU
   inference workers. **CPU-only VPS is not performance-equivalent**
   to the Mac's Metal acceleration. Translate MLX-VLM to a CUDA-capable
   documented inference adapter for the same weights/model family.
   24 GB VRAM single-GPU may be tight for several simultaneously resident
   models and KV caches; profile before buying, or use a 48 GB GPU /
   separated services. No invented latency or hosting-price claim.

## Next required hard acceptance gates

- **≥100 independently labelled Russian semantic queries** based on real
  procurement clauses, supplier tables, tender and legal material; compare
  dense, exact-match, BM25/FTS, hybrid and learned rerank at index p95.
- At least **30 adjudicated multi-page Russian documents**, with
  scans/forms/tables/stamps/unreadable pages and exact field, amount,
  OGRN/INN/OKUD preservation. OCR CER/WER and table/reading-order
  check by document class. At least 100 pages is preferable.
- **Full 8094 API E2E:** isolated namespace with create/ingest/chunk/
  embed/persist → ACL filtered hybrid search → citations → answer/
  abstention → delete/rollback, repeat and durable reload; verify
  no changes to existing customer data.
- Concurrent soak: import, query, rerank and VLM escalation while Docker
  is active; record p50/p95 stage latency, swap, unified peak, cold/hot
  start, queue depth, and long-running recovery/restart behavior.
- No production model change until comparable adoption gates, larger
  gold corpus and an explicit deployment decision.

## Suggested NEW download queue (not downloaded in this task)

| Priority | Candidate (official source) | Approx. weight | License | Rationale / risk |
|---|---|---|---|---|
| **P0** | `mlx-community/PaddleOCR-VL-1.6-4bit` | 0.68 GB | Apache-2.0 | Official community MLX conversion of downloaded 1.6 model; specialized compact OCR on Apple; benchmark full document-parser and check Russian quality |
| **P1** | `microsoft/harrier-oss-v1-0.6b` | 1.19 GB | MIT | Small multilingual dense embedding challenger; feasible to compare on the 24 GiB machine |
| **P1** | `ai-forever/FRIDA` | ~3.2 GB FP32 (0.8B params) | MIT | Native Russian search-oriented encoder, rusBEIR/ruMTEB reference; 512-token context may require shorter page chunks |

**Do not queue as commercial production candidates without licensing:**
`jinaai/jina-embeddings-v5-text-small` and
`jinaai/jina-reranker-v3.5` publish weights with
CC BY-NC 4.0 non-commercial restrictions. A separate commercial
license might be possible; do not assume permission to use these in
commercial Arvectum software.

References:
- https://www.paddleocr.ai/v3.6.0/en/version3.x/pipeline_usage/PaddleOCR-VL-Apple-Silicon.html
- https://huggingface.co/mlx-community/PaddleOCR-VL-1.6-4bit
- https://huggingface.co/microsoft/harrier-oss-v1-0.6b
- https://huggingface.co/ai-forever/FRIDA
- https://huggingface.co/jinaai/jina-embeddings-v5-text-small
- https://huggingface.co/jinaai/jina-reranker-v3.5

**Verdict:** local macOS **hybrid+Qwen4B+BGE+Gemma**, with **Tesseract
and selectively invoked Qwen3-VL-4B-MLX** is the best currently grounded
choice for a first end-to-end Data Platform testbed. Existing prod stack
unchanged while MLX OCR is a candidate, not yet deployed. Prioritize
data quality and sustained end-to-end reliability over switching
models merely because they are newer.
