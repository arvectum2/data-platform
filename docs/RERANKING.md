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
