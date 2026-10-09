# DP-MODEL-REFRESH-RU-001 — Russian-native model candidates (2026-10-09)

**Status: NOT DOWNLOADED / NOT BENCHMARKED in the previous 18-model batch.**
This corrects an omission in DP-MODEL-REFRESH-001. The prior 18/18 complete inventory is unchanged.
Do not confuse a Hugging Face model download with successfully running or evaluating it.

## Downloadable Russian-origin open-weight models (official ai-sage)

| ID | Role | Official Hugging Face repository | Frozen revision prefix | Model-weight sizes | Runtime candidate | Status |
|---|---|---|---|---:|---|---|
| GIGA-EMB-0826-480M | Embedding | `ai-sage/Giga-Embeddings-instruct-480M-0826` | `1763d603adac` | 0.967 GB (BF16) | sentence-transformers/Transformers; MLX conversion separately | DOWNLOADED + QUALITY SMOKE |
| GIGA-EMB-0826-3B | Embedding | `ai-sage/Giga-Embeddings-instruct-3B-0826` | `b71168088212` | 6.301 GB (BF16) | sentence-transformers/Transformers | NOT DOWNLOADED |
| GIGA-EMB-2025-3B | Legacy embedding baseline | `ai-sage/Giga-Embeddings-instruct` | `2cf0fdc97194` | 13.799 GB (BF16) | sentence-transformers/Transformers | NOT DOWNLOADED |
| GIGA-EMB-0826-10B | Embedding, resource-constrained candidate | `ai-sage/Giga-Embeddings-instruct-10B-A1.8B-0826` | `3bca8f1e0147` | 20.951 GB (BF16) | native Transformers; 24 GB Mac mini may be inadequate for inference | NOT DOWNLOADED |
| GIGACHAT-3.1-LIGHTNING | Generation | `ai-sage/GigaChat3.1-10B-A1.8B-GGUF` | `97045b260251` | 6.475 GB Q4_K_M | `llama.cpp` local OpenAI-compatible endpoint | NOT DOWNLOADED |

Model revisions are pinned by full HF SHA within the downloader, not by the truncated SHA shown here.
The HF model cards identify these releases as MIT; check licensing of any extra dependencies and third-party quantizations before redistributing.

**Not reasonable on a 24-GB Mac mini:** GigaChat3.1 Ultra 702B and GigaChat3.5 432B; catalogue as *remote/high-memory-only* candidates, not local download targets. Do not claim that "active MoE parameters" imply the total weights fit into RAM.

## Russian cloud API-only candidates (do not pretend to download weights)

| Vendor | Model | Benchmark path | Key qualification |
|---|---|---|---|
| Sber | `GigaEmbeddings-3B-2025-09` | GigaChat API embeddings | Hosted and distinct from public Giga-Embeddings weight repositories |
| Sber | `EmbeddingsGigaR` | GigaChat API embeddings | 2560-dimension according to current developer docs |
| Sber | GigaChat 3 Ultra / GigaChat 2 Max | GigaChat API | Hosted inference; compare cost and latency separately |
| Yandex | Yandex Text Embeddings **v2 doc + query** | Yandex AI Studio API | Query and document endpoints form one paired retrieval candidate; output dimension selectable 128/256/512/768 |
| Yandex | Alice AI LLM / Alice AI LLM Flash | Yandex AI Studio OpenAI-compatible API | Hosted generation |
| Yandex | YandexGPT Pro 5.1 / Lite 5 | Yandex AI Studio OpenAI-compatible API | Hosted generation, confirm exact model URI at test time |

Yandex's historical `yandex/yalm-100b` is public but inappropriate for local Apple Silicon inference and not a substitute for the hosted YandexGPT/Alice AI models. **Do not look for or invent local downloadable files for cloud-only models.**

References:
- https://huggingface.co/ai-sage
- https://huggingface.co/ai-sage/GigaChat3.1-10B-A1.8B-GGUF
- https://developers.sber.ru/docs/ru/gigachat/models/main
- https://aistudio.yandex.ru/ru/docs/ai-studio/concepts/embeddings
- https://aistudio.yandex.ru/ru/docs/ai-studio/concepts/generation/models

## Fair benchmark / deployment gates

1. Keep the **same immutable Russian-language corpora** for all candidates and accepted baselines: procurement forms/scans, tender clauses, contracts, supplier names, amounts, date/number preservation, formal legal language, hybrid lexical + semantic relevance, and ambiguous/insufficient-evidence answers.
2. **Embeddings:** evaluate same 45-document/12-query smoke only as preliminary; then extend to 100+ independently labelled hard queries. Compare Top-1, MRR, nDCG@5, Recall@5, p50/p95 latency, RAM and index footprint. Rebuild isolated vector indexes per embedding dimension; no production vector migration.
3. **LLM:** run the official unchanged faithfulness and Russian contract-grounding scorers; check citations, contradiction detection, abstention, hallucinations, TTFT, tokens/s and peak unified memory. Require equivalent prompts/configs and declared quantization.
4. **Hosted providers:** run *public/non-personal* documents only until vendor privacy, cross-border handling and tender-client data policy have been reviewed. Require user-authorized API credentials, per-provider cost caps, and reproducible model versions. Do not write API credentials to Git.
5. **No production promotion** before a separate decision. On 24 GB Mac mini, run one candidate at a time; optional large BF16 weight files may only be archived, not practically inferenced locally.

## Acquisition and blocker

The preceding 18/18 downloaded batch contains **zero** Giga/Yandex entries.
The deterministic local acquisition script is `scripts/download_russian_model_candidates.py`.
Run on Mac mini **only after restoring access** to `/Volumes/ArvectumSSD`, because Remote Desktop Commander's shell currently returns macOS `EPERM: Operation not permitted` when opening files on the mounted SSD (despite Unix ownership and mount appearing healthy).

Default acquisition downloads the 480M/3B 0826 embeddings and GigaChat 3.1 Lightning Q4 into the existing SSD Hugging Face cache and writes `russian-models/manifest.json`. `--all` also archives the legacy 2025 3B and 10B 0826 candidate. The downloader verifies every downloaded model weight's expected byte count and hashes its bytes, without changing running model services.

## Observed first local quality result (2026-10-09)

Giga-Embeddings 480M BF16 is present and SHA-256 verified in the SSD manifest. On the exact 45 Arvectum Site pages and 12 frozen observed Russian GSC/Yandex queries, its pure dense ranking gave **Top-1 0.500**, **MRR 0.711**, **Recall@5 1.000** and **nDCG@5 0.784**, with 1024 dimensions. See `docs/GIGA_EMBEDDINGS_FIRST_BENCHMARK_2026-10-09.md` for reproducibility and caveats. The 3B download had been stalled after about 2.31 GiB; the Hugging Face downloader was restarted with its fallback HTTP transfer on 2026-10-09. **No larger model is marked ready without verified full weights.**
