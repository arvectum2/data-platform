# Schema-driven structured extraction

DP-STRUCT-001 exposes the existing evidence-first extraction engine as a production schema-driven service.

Consumers submit a field schema to `POST /v1/extract`. Each field declares a key, optional aliases, required/review thresholds and a value type: `string`, `integer`, `number` or `boolean`.

The deterministic `AutoDiscoveryProvider` runs first and extracts candidates from structured attributes, JSON-LD, HTML metadata/semantic elements, label-value structures and text. Values are type-coerced centrally before resolution. Values that cannot satisfy the requested type are discarded rather than silently treated as facts.

Every decision exposes:
- status (`auto_selected`, `needs_confirmation`, `unresolved`, etc.);
- selected value, confidence and provider;
- all candidate IDs;
- evidence kind, source reference, excerpt and metadata for every candidate.

The API therefore distinguishes confident facts from review-required or unresolved fields.

## Optional model extraction

Set `use_model=true` to add `ReasoningCandidateProvider` when the DP-MODEL reasoning role is configured. There is no implicit remote fallback.

The model is instructed to return only source-supported values and a verbatim evidence excerpt. Model candidates whose excerpt cannot be found in the supplied source are rejected before resolution. Provider failures are isolated and reported in `provider_errors`; deterministic extraction continues.

URL extraction uses the same provider boundary after governed acquisition. Model use remains explicit.

## Safety and activation

Deterministic extraction is the default. Model extraction is optional and policy-controlled. Confidence thresholds and candidate margins remain consumer-defined. Required fields that cannot be supported remain unresolved.
