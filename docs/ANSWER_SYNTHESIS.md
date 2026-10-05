# Evidence-grounded answer synthesis

DP-ANSWER-001 adds an optional synthesis layer on top of retrieval without weakening the Data Platform source-of-truth boundary.

`POST /v1/answer` performs normal governed search first and supplies only the bounded returned `SearchHit` set to the configured reasoning provider. The model cannot fetch additional context through this path.

Every material claim must cite one or more `chunk_id` values from that exact evidence set. Responses citing unknown chunks are rejected. The response preserves the full retrieval evidence, scores, collection metadata and canonical URIs alongside:
- answer text;
- claim-level chunk citations;
- contradictions;
- uncertainty;
- explicit abstention state.

If no reasoning provider is configured, no evidence exists, or synthesis fails validation, the service abstains instead of inventing an answer. Retrieval evidence remains available to the consumer.

Reasoning remains optional and follows DP-MODEL locality/allowlist policy. Raw `/v1/search` is unchanged and never requires an LLM.

## Faithfulness gate

Retrieval relevance and answer faithfulness are separate concerns. Production activation should measure at minimum:
- citation validity: every cited chunk belongs to supplied evidence;
- claim support: each material claim is supported by its cited chunk(s);
- contradiction recall on frozen conflicting-source cases;
- abstention correctness on insufficient-evidence cases;
- synthesis latency separately from retrieval latency.
