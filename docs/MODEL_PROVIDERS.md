# Model provider layer

DP-MODEL-001 adds optional, product-neutral model roles without making generation a dependency of indexing or search.

## Roles

- **embedding** remains configured independently by the existing embedding provider layer;
- **reasoning** uses the text-generation contract;
- **vision** uses the VLM contract.

Reasoning and vision are disabled by default. Search, ingestion and indexing remain available when either role is disabled or unavailable.

## Deployment policy

Each optional role has one policy:

- `disabled`: no provider exists for the role;
- `local-only`: only a loopback OpenAI-compatible endpoint is accepted;
- `remote-allowlist`: a remote provider is accepted only when its endpoint hostname appears in that role's explicit allowlist.

There is no implicit fallback from a local provider to a remote provider. Retries only target the configured endpoint.

The initial transport is OpenAI-compatible `/v1/chat/completions`, which allows llama.cpp and other compatible local runtimes to attach without consumer-specific code. Vision requests use OpenAI-compatible text + `image_url` content blocks.

## Diagnostics and readiness

`GET /v1/status` reports configured model role identity, model/version, locality, capabilities and bounded aggregate metrics. It does not make network probes.

`GET /v1/models/status?probe=true` actively probes the configured endpoint through `/v1/models`. Probe output records readiness, latency and error type but never prompt/document content.

Provider metrics contain only request/success/error counts, aggregate latency, token usage returned by the provider, and error classes. Prompts and documents are not logged.

## Runtime controls

Generation providers enforce:

- bounded request timeout;
- bounded retry attempts with exponential delay;
- bounded concurrency using a semaphore;
- independent reasoning and vision model/endpoint/version configuration.

A provider response carries provider/model/version/locality identity so future derived artifacts can preserve model provenance.
