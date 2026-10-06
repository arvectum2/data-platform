# Optional reranking

DP-RERANK-001 adds an opt-in second-stage reranker after deterministic lexical/vector fusion.

## Contract

The hybrid engine first retrieves and fuses candidates exactly as before. When `rerank=true`, only the first `rerank_candidates` fused hits are exposed to the reranker. The reranker cannot retrieve new documents.

Every result keeps the original `lexical`, `vector` and `fusion` scores. A separate nullable `rerank` score records the second-stage score. This keeps ranking decisions inspectable.

The default is `rerank=false`. If reranking is requested but no reasoning provider is configured, deterministic hybrid ranking remains active. Provider failures, malformed JSON and empty rerank responses also fail open to the original order.

## Reasoning provider

The first implementation uses the DP-MODEL-001 reasoning provider. It requests strict JSON containing only supplied chunk IDs and scores from 0 to 1. Unknown IDs, duplicate IDs and invalid scores are discarded.

The candidate set is bounded both by the API request and by the reranker implementation. Candidate text is truncated before model submission.

## Benchmark gate

Reranking must not become a default production behavior merely because a model is available. `RerankGate` compares the same frozen evaluation suite before and after reranking.

Initial gate:
- MRR gain >= 0.01;
- top-1 accuracy must not regress;
- p95 latency must stay <= 3x baseline.

The current production acceptance v3 baseline is already 20/20 top-1 with MRR 1.0, so an LLM reranker cannot demonstrate a positive MRR gain on that suite. It therefore remains opt-in. A harder frozen relevance suite is required before any default activation decision.

## Hard-suite acceptance — 2026-10-06

The real Search Console/Yandex suite growth_search_console_v1 is suitable for
a reranking decision because base hybrid retrieval is not saturated:

- top-1 accuracy: 0.50;
- MRR: 0.5833;
- mean nDCG@5: 0.6468;
- p95 search latency: about 251 ms on the measured run.

The local Gemma reasoning reranker was then tested with only 5 candidates,
rather than the normal upper bound of 20. The rerank request still exceeded a
5-second client timeout before the suite could complete. Under the existing
gate, reranked p95 must stay <=3x the baseline, which is about 752 ms for this
run. Therefore the current local LLM reranker fails the latency gate by a wide
margin before quality uplift even becomes relevant.

This is a benchmark result, not a removal of the feature. rerank=true remains
available as an explicit opt-in, but default activation is rejected. A lighter
learned/cross-encoder reranker can be evaluated later against the same frozen
suite and gate.

## Learned cross-encoder candidate

A provider-neutral `CrossEncoderReranker` is available as a benchmark candidate. It scores only the already-retrieved bounded candidate set and cannot retrieve or inject new documents. Provider/model identity is exposed through the same safe rerank diagnostics as the reasoning reranker.

The optional `SentenceTransformersCrossEncoderScorer` uses a lazy import, so sentence-transformers/torch are not mandatory runtime dependencies and default deployments are unchanged. No cross-encoder is enabled automatically.

The accepted local candidate is `BAAI/bge-reranker-v2-m3`: multilingual and commercially usable under Apache-2.0. It passed the hard frozen-suite nDCG/MRR and latency gate and is the preferred strategy when reranking is explicitly enabled.

## Cross-encoder live promotion result

On 2026-10-06 the hard `growth_search_console_v1` suite was rerun on the Mac mini with `BAAI/bge-reranker-v2-m3` after one explicit warm-up. The accepted configuration reranks only the top 3 candidates and truncates candidate text to 1000 characters.

- baseline: top-1 0.50, MRR 0.5833, mean nDCG@5 0.6468, p95 126.8 ms;
- cross-encoder: top-1 0.5833, MRR 0.6667, mean nDCG@5 0.6885, p95 276.6 ms;
- gain: +0.0833 MRR, +0.0833 top-1, +0.0417 mean nDCG@5;
- latency multiplier: 2.18x, inside the existing <=3x promotion gate.

The learned/cross-encoder candidate therefore passes the benchmark promotion gate. A separate warm-process measurement put physical footprint at about 3.74 GB with a ~3.87 GB peak on the 24 GiB Apple Silicon host. API integration and isolated localhost sidecar packaging are now deployed; invocation still remains opt-in through `rerank=true`. The frozen result is `benchmarks/results/cross_encoder_rerank_2026-10-06.json`.

## BGE live acceptance — 2026-10-06

The first concrete learned candidate, `BAAI/bge-reranker-v2-m3` (Apache-2.0), was measured on the 12-case `growth_search_console_v1` hard suite on the Mac mini in a separate benchmark virtual environment. After three warm-up passes and with 5 candidates capped at 800 characters, baseline hybrid scored top-1 0.500, MRR 0.5833, nDCG@5 0.6468 and p95 134.6 ms. The cross-encoder scored top-1 0.5833, MRR 0.6667, nDCG@5 0.6885 and p95 334.2 ms.

That is +0.0833 top-1, +0.0833 MRR, +0.0417 nDCG@5 and a 2.48x p95 multiplier. It passes the frozen rerank promotion gate: MRR gain >= 0.03, top-1 gain >= 0.05 and p95 <= 3x baseline.

Decision: accept BGE as the preferred optional learned reranker. Runtime packaging is isolated from the core API service through the localhost sidecar, so sentence-transformers/torch remain outside FAST/local-core dependencies. `rerank=false` stays the request default; `cross_encoder` is the default strategy once reranking is enabled.

## Production sidecar activation

The accepted BGE reranker is packaged as a separate localhost-only sidecar rather than importing Torch into the core Data Platform environment. `scripts/reranker_server.py` loads `BAAI/bge-reranker-v2-m3` once, warms the model before serving, bounds request size/pair count and exposes only `GET /health` plus `POST /score` on loopback.

Core Data Platform uses the lightweight `HttpCrossEncoderScorer` and therefore keeps `sentence-transformers`/Torch out of the mandatory server dependencies. Default cross-encoder settings point to `http://127.0.0.1:8091`, top-3 candidates, 1000 candidate characters and a 1 second sidecar timeout.

`rerank=false` remains the API default, so FAST/core behavior is unchanged. When reranking is explicitly enabled and no strategy is supplied, `cross_encoder` is now preferred. The previous reasoning/LLM path remains available with `rerank_strategy=reasoning`.

Sidecar failure is fail-open: timeout, connection failure, malformed scoring output or an unavailable model leaves the original deterministic hybrid ordering intact and reports the rerank stage as `failed-open`/unavailable in diagnostics. LOCAL_PRIVATE additionally rejects a non-loopback cross-encoder endpoint.


## Production runtime acceptance — 2026-10-06

The Mac mini production deployment runs `com.arvectum.reranker` on `127.0.0.1:8091` and Data Platform on `127.0.0.1:8094`. The sidecar performs three production-shape warm-up passes before opening the socket, so torch/Metal compilation cost is paid at startup rather than on the first search.

A live STANDARD search for the frozen `gsc-supplier-selection` case, with `rerank=true`, `rerank_candidates=3` and no explicit strategy, selected the cross-encoder automatically. The base hybrid order placed the procurement page third; BGE promoted it to first. Observed rerank stage latency was 242 ms on the initial acceptance run and 219 ms on the post-restart re-check; total search was 287 ms and 285 ms respectively, both inside the 1500 ms STANDARD budget.

Fail-open was tested by fully booting out the reranker launch agent. The same API request still returned HTTP 200, reported `rerank_status=failed-open` in ~0.9 ms, preserved null rerank scores and completed in ~55 ms using deterministic hybrid ordering. The launch agent was then restored, health returned `ok`, and a second live request again reported `rerank_status=executed` with the accepted top-1.
