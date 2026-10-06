# Capability / effort modes

DP-MODES-001 exposes product-neutral execution-depth envelopes. A mode limits
which stages a consumer may request; it does not silently enable a model-backed
stage whose benchmark gate has failed.

Requests that omit execution_mode preserve the existing 1.x behavior.

## FAST

Endpoint: /v1/search.

Baseline: lexical/vector retrieval plus deterministic fusion. Automatic query
expansion and reranking are forbidden. No generative model is required.

## STANDARD

Endpoint: /v1/search.

Baseline remains deterministic hybrid retrieval. Bounded reranking is allowed
only when the consumer explicitly requests it, with at most 20 candidates.
Automatic query expansion is forbidden. If reranking is unavailable or fails,
the existing search engine falls back to deterministic ordering.

The current local LLM reranker has not passed its promotion gate, so STANDARD
does not turn it on automatically.

## DEEP

Endpoint: /v1/search.

Consumers may explicitly request query expansion and/or reranking. The mode
caps automatic expansion at four variants and reranking at 20 candidates.
Those features remain opt-in because current benchmark evidence does not justify
default promotion. Provider failures retain the existing fail-open deterministic
retrieval behavior.

## RESEARCH

Endpoint: /v1/research.

The existing governed workflow provides discovery, acquisition, indexing,
retrieval, contradiction-aware grounded synthesis and explicit abstention.
Discovery remains bounded to 25 sources and returned evidence to 50 items. When research reranking is explicitly requested, the existing workflow can rerank at most those 50 bounded evidence candidates.
If reasoning is unavailable, evidence is preserved and synthesis abstains.

## Discovery

GET /v1/modes returns the four envelopes, baseline/optional stages, resource
caps and safe-degradation description. The response contains no provider secret,
prompt text or document content.

These are capability ceilings, not model names. Local and remote provider
choices remain governed independently by DP-MODEL-001 policy.

## Search execution diagnostics

Search responses now include a diagnostics object. The engine reports aggregate
duration and status for the stages it actually attempted:

- query expansion;
- lexical retrieval;
- query embedding;
- vector retrieval;
- fusion;
- product ranking when configured;
- reranking;
- total search.

Model-backed stages distinguish executed, skipped-unavailable and failed-open.
Provider/model identity is included where available. Metadata is deliberately
limited to safe counters such as call count, candidate limit, variant count and
returned-hit count. Query text, document text, URLs, API keys and exception
messages are not copied into diagnostics.
