# DP-MODEL-REFRESH-001 — first local Russian quality comparison (2026-10-09)

**Outcome:** controlled candidate evaluation complete for the first representative
group. **No production model/index/provider changes.** The official release
promotion gate remains open, and downloads of 18 models are not equivalent to
testing all 18 on quality.

## Inputs, isolation and reproducibility

- Hardware: Apple Silicon Mac mini, 24 GB unified memory, macOS.
- Weights: `/Volumes/ArvectumSSD/Models/data-platform-benchmarks/`.
  `audit_results.json` has SHA-256 for all 24 weight files.
- Local Arvectum Site checkout at commit `cf1261e`: **45 HTML pages**.
  We use title, meta description and the first 1700 characters of visible
  `<main>` text per document, hashed into each embedding result.
  This is a **document-level dense-only** relevance comparison, not a hybrid
  retriever or a reproduction of the production index.
- Queries: the original 12 observed Search Console/Yandex cases from the
  unchanged `benchmarks/growth_search_console_v1.json`, each with an existing
  expected canonical URL. The suite hash is recorded.
- OCR: the **two human-reviewed** public_v2 scanned procurement PDFs, with
  unchanged manifest and gold hashes. No AI-generated truth.
- Grounded Russian answer tests: unchanged 5 real-source cases from
  `benchmarks/faithfulness_real_v1.json`.
- Original detailed scores and individual case outcomes:
  `benchmarks/results/model_refresh_2026-10-09/`.

## A. Qwen3 embeddings: same corpus, GGUF, llama.cpp

| Model | Dimension | Top-1 | MRR | Recall@5 | nDCG@5 | Embedding time* |
|---|---:|---:|---:|---:|---:|---:|
| Qwen3-Embedding-0.6B Q8_0 | 1024 | 0.583 | 0.726 | 0.833 | 0.741 | 6.37 s |
| **Qwen3-Embedding-4B Q8_0** (incumbent) | 2560 | **0.667** | **0.785** | 0.917 | **0.808** | 35.50 s |
| Qwen3-Embedding-8B Q4_K_M | 4096 | 0.583 | 0.732 | **1.000** | 0.798 | 71.39 s |

*Total embedding time for 45 docs and 12 queries, including local HTTP
overhead and batches of 3. Small single-run workload, not production
throughput or end-to-end latency. Q8 and Q4 are **not equal quantizations**.
Search metrics are computed using cosine similarity in separate, ephemeral
model-specific vector arrays. No vectors were written to Postgres.

**Finding:** 4B remains the most balanced of the three on these 12 queries;
8B finds all expected pages within the top five but often ranks another
page first. A single 12-query exploratory corpus is insufficient for
statistical significance or global promotion/rejection.

## B. Reranking: same 4B dense top-five, 12 queries

| Stage | Top-1 | MRR within top-five | nDCG@5 | Median score latency |
|---|---:|---:|---:|---:|
| Unchanged Qwen3-Embedding-4B dense top-five | 0.667 | 0.771 | 0.808 | — |
| Existing BGE-reranker-v2-m3 sidecar | 0.667 | **0.778** | **0.813** | **0.279 s** |
| Qwen3-Reranker-0.6B CrossEncoder on CPU | 0.667 | 0.746 | 0.787 | 7.588 s |

This rerank measurement uses the exact same *five dense candidates* in each
query, truncating each candidate to 800 characters. Ranking mistakes outside
top-five are unrecoverable. The MRR baseline differs from full dense retrieval
because this table only evaluates the bounded top-five. BGE uses the **existing
production scorer**, whereas the Qwen candidate ran in a CPU benchmark venv;
their latency values are **not** equal-hardware or equal-backend measurements.
The Qwen model did not show enough extra relevance to justify promoting it.

## C. OCR: two Russian PDF scans, frozen human-reviewed gold

| Model | Mean CER ↓ | Mean WER ↓ | Required strings | Mean seconds/page ↓ |
|---|---:|---:|---:|---:|
| Tesseract rus+eng, PSM3 | 0.2140 | 0.2975 | 2/2 | **0.83** |
| Qwen3-VL-4B-Instruct Q4_K_M, llama.cpp + mmproj | **0.1545** | **0.2293** | 2/2 | 19.45 |

- The difficult procurement form CER dropped from **0.4058 to 0.2939**;
  the linear specification CER dropped from **0.0223 to 0.0150**.
- Existing OCR-first routing stays valid: escalate only poor-confidence /
  structurally difficult pages to VLM.
- Two scanned pages are insufficient for broad OCR suitability. Table,
  cell, reading-order and hallucination checks require human review.
- For this specific Tesseract experiment, using a macOS temporary folder
  under `/tmp` failed to open images; staging images under ArvectumSSD
  fixed the reproducibility issue. This runner uses `pdfimages` and
  Tesseract PSM3, so its baseline differs from the older public-v1 runner.

## D. Qwen3.5 Russian grounded-answer exploratory smoke

| MLX 4-bit model | Cases meeting required terms, citation IDs and abstention heuristic | Mean synthesis time |
|---|---:|---:|
| Qwen3.5-4B | 5/5 | **0.925 s** |
| Qwen3.5-9B | 5/5 | 1.555 s |

Each model sees the unchanged five real-source faithfulness questions and
evidence. The local uniform prompt requests exact amounts, source IDs and
an abstention when the documents do not contain an answer. Both returned
expected terms and citations and abstained on the missing-bank-BIK case.

**Important:** these are *automated lexical/structural checks* on a handful
of short answers; they are **not** the established Gemma 4 official
claim-support/hallucination benchmark and they do not establish equivalence
to its accepted 1.0 gates. The models have not been promoted.

## Recommended serving integration

Retain `llama.cpp` for currently deployed Qwen3-Embedding-4B and Gemma 4
endpoints; retain the existing BGE scoring sidecar and Tesseract. The
low-risk candidate route for Qwen3.5 is MLX if a future full faithfulness
suite supports promotion. Qwen3-VL-4B via `llama.cpp` has demonstrated
vision/OCR support and is a viable *escalation experiment*, not a substitute
for local deterministic extraction.

## Reproduce on Mac mini

All scripts are read-only relative to Data Platform production services.
They start/stop their own model servers on ephemeral loopback ports.

```bash
cd /Volumes/ArvectumSSD/Arvectum/repos/data-platform
OUT=/Volumes/ArvectumSSD/Models/data-platform-benchmarks/quality-results
python3 scripts/benchmark_embedding_refresh.py --model 0.6b --output "$OUT/embedding-0.6b.json"
python3 scripts/benchmark_embedding_refresh.py --model 4b --output "$OUT/embedding-4b.json"
python3 scripts/benchmark_embedding_refresh.py --model 8b --output "$OUT/embedding-8b.json"
python3 scripts/benchmark_ocr_refresh.py --output "$OUT/ocr-qwen3vl4b-vs-tesseract.json"
# Qwen reranker requires the isolated cross-encoder venv and live local BGE scoring sidecar:
/Users/master/arvectum-runtime/data-platform-reranker/.venv/bin/python scripts/benchmark_reranker_refresh.py --dense-results "$OUT/embedding-4b.json" --output "$OUT/reranker-qwen3-0.6b-vs-bge.json"
python3 scripts/benchmark_reasoning_refresh.py --model 4b --output "$OUT/reasoning-qwen35-4b.json"
python3 scripts/benchmark_reasoning_refresh.py --model 9b --output "$OUT/reasoning-qwen35-9b.json"
```

## Open promotion work, deferred safely

1. Extend OCR beyond two scans and independently review field/value and
   table order output on Russian forms; evaluate PaddleOCR-VL-1.6,
   dots.ocr, DeepSeek-OCR, Qwen3-VL-8B under dedicated native adapters.
2. Compare BGE-M3 with existing embeddings on a frozen, larger
   *document-level* Russian procurement corpus using separate dimensions.
3. Benchmark Qwen3-Reranker-4B and 0.6B on comparable accelerated
   backends against BGE; avoid running large Torch models beside current
   production without a resource budget.
4. Run Qwen3.5 candidates through the **same official faithfulness scorer**
   used for Gemma 4 and a larger human-adjudicated corpus before switching.
5. Re-run final adoption gates on an isolated production-like deployment
   with reproducible configs, memory telemetry, and at least 100 labeled
   difficult cases before changing a production model.

**Decision:** no change for production. Continue development of Data Platform;
model migration is still an optimization stage gated by reliable benchmarks.
