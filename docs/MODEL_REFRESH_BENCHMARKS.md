# DP-MODEL-REFRESH-001 — October 2026 candidate batch

Status: **STAGED FOR EVALUATION; NOT PROMOTED**. Benchmark-only model downloads live at
`/Volumes/ArvectumSSD/Models/data-platform-benchmarks/`, with `manifest.json`
recording local paths, partial/ready state and exact snapshots. This is a
reconstructed candidate shortlist: it was **not** present as a concrete table
in the previously committed ROADMAP, and must not be confused with accepted
production models or benchmark results.

## Existing quality baseline (no change to production)

| Role | Baseline | Current integration |
|---|---|---|
| Embeddings | Qwen3-Embedding-4B Q8_0 | llama.cpp OpenAI embeddings, 127.0.0.1:8090 |
| Reranking | BAAI/bge-reranker-v2-m3 | sentence-transformers sidecar, 127.0.0.1:8091 |
| Reasoning / answer synthesis | Gemma 4 12B QAT Q4 | llama.cpp, 127.0.0.1:8081 |
| Scanned documents | local Tesseract rus/eng | deterministic OCR-first policy |
| Vision fallback | Qwen2.5-VL-3B-Instruct-4bit | former MLX comparison only, not production |

## Candidate matrix

| Role | Candidate | Comparison purpose | Preferred runtime |
|---|---|---|---|
| Embedding | Qwen3-Embedding-0.6B Q8_0 | compact speed/resource baseline | llama.cpp |
| Embedding | Qwen3-Embedding-4B Q8_0 | incumbent quality reference | llama.cpp |
| Embedding | Qwen3-Embedding-8B Q4_K_M | larger-model relevance headroom | llama.cpp |
| Embedding | BAAI/bge-m3 | multilingual dense/sparse alternative | FlagEmbedding/sentence-transformers |
| Rerank | BAAI/bge-reranker-v2-m3 | accepted learned baseline | dedicated scorer |
| Rerank | Qwen3-Reranker-0.6B | lightweight pairwise scorer | transformers |
| Rerank | Qwen3-Reranker-4B | heavyweight quality challenger | transformers |
| Generation | Gemma 4 12B QAT Q4 | incumbent groundedness baseline | llama.cpp |
| Generation | Qwen3.5-4B MLX 4bit | compact Russian-language synthesis | mlx-lm |
| Generation | Qwen3.5-9B MLX 4bit | higher-capacity synthesis | mlx-lm |
| Vision | Qwen2.5-VL-3B MLX 4bit | previous controlled VLM reference | mlx-vlm |
| Vision | Qwen2.5-VL-7B GGUF | larger previous-generation VL | llama.cpp |
| Vision | Qwen3-VL-4B MLX/GGUF | current vision baseline, compare formats | mlx-vlm / llama.cpp |
| Vision | Qwen3-VL-8B MLX 4bit | larger form/layout reasoning | mlx-vlm |
| OCR/layout | PaddleOCR-VL-1.6 | specialized document parsing | PaddleOCR native |
| OCR/layout | rednote-hilab/dots.ocr | document structure and OCR | transformers/custom |
| OCR/layout | deepseek-ai/DeepSeek-OCR | document OCR challenger | transformers/custom |

The candidate list is a **download/evaluation plan**, not an empirical ranking or a claim
that every upstream inference implementation supports macOS Metal. Dedicated code paths
may be required for PaddleOCR/dots.ocr/DeepSeek-OCR. Check licenses before product
redistribution. The `manifest.json` is the source of truth for weight availability.

## Evaluation protocol before any switch

1. Preserve frozen, human-reviewed *Russian* procurement/business corpus, visual OCR truth, source hashes and provenance; add hard handwritten forms/tables only with independent human ground truth.
2. For embeddings evaluate search top-1, Recall@5, MRR, nDCG, lexical+vector hybrid, ru semantic queries, latency and indexing cost. **Different embedding dimensions require isolated indexes**; do not silently overwrite existing production vectors.
3. For OCR/VLM evaluate CER/WER, field-value pair integrity, tables, layout, reading order, escalation precision/recall, peak unified RAM and seconds/page.
4. For rerank evaluate nDCG/MRR uplift at p95 latency and RAM budgets versus BGE. For generation evaluate cited claim support, abstention, contradiction handling and RU factual synthesis.
5. Benchmark **model quality** on shared corpora before comparing **serving runtimes**: only compare Ollama, LM Studio and llama.cpp on identical weights/quantization, context size, prompts, Metal offload and warm-up. The MLX format is a separate baseline.
6. On 24-GB Mac mini, run large contenders one at a time and keep live ports/services unchanged; do not activate new models by default without measured promotion gates and an explicit rollout decision.

Decision deferred until after core product delivery, consistent with the
existing benchmark-driven architecture and postponed optimization phase.
