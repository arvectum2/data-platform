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
