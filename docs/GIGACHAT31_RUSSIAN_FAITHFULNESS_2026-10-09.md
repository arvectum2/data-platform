# GigaChat 3.1 Lightning GGUF — first frozen Russian faithfulness smoke (2026-10-09)

**Status:** local model weights verified and read-only experiment completed.
**No promotion to production.**

## Candidate and runtime

- `ai-sage/GigaChat3.1-10B-A1.8B-GGUF`
- Immutable Hugging Face revision `97045b260251cfa86f5ad25638fa2dd074153446`
- GGUF file `GigaChat3.1-10B-A1.8B-q4_K_M.gguf`, 6.475 GB;
  SHA-256 in the SSD `russian-models/manifest.json`.
- Tested locally on the existing 24 GB Mac mini using a temporary, isolated
  `llama.cpp` server on port 18099 with Metal acceleration; the benchmark
  stopped the temporary server after evaluation.
- Reproducible runner: `scripts/benchmark_gigachat_reasoning_refresh.py`.

## Frozen evidence and scoring

Uses **exactly the same five** frozen
`benchmarks/faithfulness_real_v1.json` cases and system/user instruction
text as the earlier **Qwen3.5-4B/9B MLX** exploratory comparisons.
Evaluates three automated checks:

1. Exact lexical presence of human-accepted required answer fragments,
   especially organization names, OKUD/OKPD2 codes and amounts;
2. Citation references to the provided evidence chunk IDs;
3. Abstention when the evidence does not contain the answer (including
   no fabricated 9-digit bank BIK).

This **is not** the full accepted Data Platform faithfulness scorer, and
it does not prove absence of unsupported claims outside the expected
fragments. Qwen uses MLX 4-bit, GigaChat uses GGUF Q4; serving-time
results are not a controlled equal-backend performance comparison.

## Results

| Local generation candidate | Exact-answer terms | Correct citation checks | Abstention checks | Combined pass | Mean response time |
|---|---:|---:|---:|---:|---:|
| **GigaChat 3.1 Lightning Q4_K_M GGUF** | **3/5** | 5/5 | 5/5 | **3/5** | 0.930 s |
| Qwen3.5-4B MLX 4-bit (previous local smoke) | 5/5 | 5/5 | 5/5 | 5/5 | 0.925 s |
| Qwen3.5-9B MLX 4-bit (previous local smoke) | 5/5 | 5/5 | 5/5 | 5/5 | 1.555 s |

**Two GigaChat exact-string failures:**
`real-control-authority-okud` and
`real-multisource-control-and-nmck`.
The candidate returned **`Комитет финансов Санкт- Петербурга`**
(with an extra space after the hyphen), whereas the source explicitly says
**`Комитет финансов Санкт-Петербурга`**. The other required fields,
including exact amounts, OKUD/OKPD2 values, source citations and
insufficient-evidence abstention, passed the automated checks.

This is a *formatting/fidelity mismatch*, not evidence of a fabricated
organization or a wrong numerical value. It is nevertheless relevant to
tender-document fidelity gates where exact legal names matter. These
preliminary results do not establish full groundedness beyond checked
claims. Larger independently reviewed Russian data and the official
faithfulness suite remain required before a deployment decision.

## Data and reproduction

Per-case raw model answers and scores:
`benchmarks/results/model_refresh_2026-10-09/gigachat31-5case.json`.

```bash
cd /Volumes/ArvectumSSD/Arvectum/repos/data-platform
python3 scripts/benchmark_gigachat_reasoning_refresh.py \
  --output /Volumes/ArvectumSSD/Models/data-platform-benchmarks/quality-results/gigachat31-5case.json
```

**Decision:** keep Gemma 4 as the current production reasoning service.
Further model evaluation is a separate, benchmark-gated effort and
must not silently change production endpoints or stored embeddings.
