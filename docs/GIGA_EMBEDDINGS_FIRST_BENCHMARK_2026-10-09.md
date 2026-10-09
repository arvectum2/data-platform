# Russian model refresh — first Giga-Embeddings local benchmark (2026-10-09)

**Model run:** `ai-sage/Giga-Embeddings-instruct-480M-0826`, revision
`1763d603adac8057bd6482a708001b0ed2e0a903`.
Official BF16 weight, 967,470,272 bytes, SHA-256
`9ce03c6c5ae02baebb42ce3015b6f3e628c5fec7b7745bc2490f6ff961a654a5`.
The model was downloaded and verified to ArvectumSSD and ran locally with
`sentence-transformers` on PyTorch MPS on the 24 GB Mac mini.

This is an **initial small Russian search experiment**, **not** a production
acceptance gate or a model promotion.

## Equal benchmark input and evaluation

- Same `benchmarks/growth_search_console_v1.json`: **12 real Russian
  site-search queries**, unchanged expected canonical document URLs and test
  SHA-256.
- Same Arvectum Site checkout `cf1261e`: **45 HTML pages**, same
  first 1700 characters of visible page title, description, and main text.
  The exact corpus SHA-256 matches the original Qwen results.
- Same pure dense-cosine document-level top-1/MRR/Recall@5/nDCG@5.
  Embeddings and scores are kept in temporary Python arrays, never written
  to production Postgres indexes.
- Giga uses its **official model-native preprocessing**:
  mean-pooling + L2 normalization, query instruction
  `Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: ...`;
  documents do not receive instructions.
- Prior Qwen baselines used their original **no-instruction** queries.
  Thus this is the same retrieval corpus/labels, but not identical prompt
  conditioning. Serving runtimes also differ; timing is *informative*, not a
  strictly controlled cross-runtime benchmark.

## Results

| Embedding model | Dimension | Top-1 | MRR | Recall@5 | nDCG@5 | Total encode time¹ |
|---|---:|---:|---:|---:|---:|---:|
| **Giga-Embeddings 480M BF16** (native Torch/MPS) | 1024 | 0.500 | 0.711 | **1.000** | 0.784 | **4.58 s** |
| Qwen3-Embedding 0.6B GGUF Q8_0 (llama.cpp) | 1024 | 0.583 | 0.726 | 0.833 | 0.741 | 6.37 s |
| **Qwen3-Embedding 4B GGUF Q8_0** (current baseline) | 2560 | **0.667** | **0.785** | 0.917 | **0.808** | 35.50 s |
| Qwen3-Embedding 8B GGUF Q4_K_M (llama.cpp) | 4096 | 0.583 | 0.732 | **1.000** | 0.798 | 71.39 s |

¹ Sum of embedding 45 page inputs and 12 queries; does not include startup,
index writing, network ingestion, or recall/answer generation. Hardware was
the same, but model architectures, quantizations, backends, batch behavior,
and prompt configurations were **not**, so do not interpret these times as
controlled inference-speed superiority.

**Observation:** this small Giga model retrieves every target within top
five, which is encouraging for later reranking and for resource-limited
deployments, but its top-1 is below Qwen3-Embedding-4B on these 12 queries.
No significance claims are possible from 12 cases. Current 4B model remains
the accepted production baseline.

Full machine-readable per-case results:
`benchmarks/results/model_refresh_2026-10-09/giga-embeddings-0826-480m.json`.
Replay with:
```bash
cd /Volumes/ArvectumSSD/Arvectum/repos/data-platform
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false \
  /Users/master/arvectum-runtime/data-platform-reranker/.venv/bin/python \
  scripts/benchmark_giga_embeddings_refresh.py --device mps \
  --output /Volumes/ArvectumSSD/Models/data-platform-benchmarks/quality-results/giga-embeddings-0826-480m.json
```

## Download status and next comparison

At 09:52 MSK on 2026-10-09, the original `--all` downloader was running,
but only 480M was `ready`. The 3B safetensors download had reached about
2.31 GiB, with the unfinished weight file last modified at 09:02 MSK.
The process was still present but sockets to local proxy :8080 appeared closed,
indicating a stalled transfer rather than demonstrated ongoing progress.
Do not score 3B, 10B, or GigaChat before their actual files pass the manifest
size/hash checks.

Once Giga-Embeddings 3B and GigaChat 3.1 Lightning Q4 are available, replay
the same frozen Russian retrieval and grounded-answer cases, respectively.
Sber and Yandex hosted models require an independent API-cost, credentials,
privacy and region review, and do **not** have downloadable hosted weights.

**Decision:** no production provider change, no embedding dimension change,
no changes to accepted runtime endpoints.

## Follow-up: Giga-Embeddings 3B BF16 is now verified and benchmarked

The `ai-sage/Giga-Embeddings-instruct-3B-0826` revision
`b71168088212f0a13688514e4fc288a86106c4e4` has finished downloading.
The downloader verified its **6,301 MB** weight-file byte count, computed
SHA-256 and marked the snapshot **ready**. Unlike the smaller 480M model,
the 3B output dimension is **2048**. It ran successfully with PyTorch MPS
using the same model-native query instruction and mean/L2 pooling.

| Model | Dim | Top-1 | MRR | Recall@5 | nDCG@5 | Total encode time |
|---|---:|---:|---:|---:|---:|---:|
| Giga-Embeddings 480M BF16 | 1024 | 0.500 | 0.711 | 1.000 | 0.784 | 4.58 s |
| **Giga-Embeddings 3B BF16** | 2048 | 0.583 | 0.742 | **1.000** | **0.806** | 19.89 s |
| Qwen3-Embedding 4B Q8 GGUF (incumbent) | 2560 | **0.667** | **0.785** | 0.917 | **0.808** | 35.50 s |

The Giga 3B score is **nearly tied with incumbent 4B on nDCG@5**,
but Qwen3 4B has higher MRR and top-1. The 3B achieved full recall
within the first five in this small evaluation. Different engine/format
and query-instruction caveats above still apply.

Both Russian embeddings were evaluated on *exactly* the same site and
accepted query labels (verified equal corpus and suite SHA-256 hashes).
Per-case scores are stored at
`benchmarks/results/model_refresh_2026-10-09/giga-embeddings-0826-3b.json`.
The combined machine-readable five-model table lives at
`benchmarks/results/model_refresh_2026-10-09/russian_embeddings_comparison.json`.

**Download recovery:** The first 3B transfer stopped advancing after
2.31 GiB. The stalled process was gracefully stopped, and a new
Hugging Face HTTP (non-XET) transfer completed and validated the
3B file. The downloader is continuing through its remaining queue.
Do not treat the downloading GigaChat checkpoint as ready before the
manifest confirms full file and checksum validation.
