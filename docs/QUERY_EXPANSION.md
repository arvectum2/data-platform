# Query expansion

DP-QE-001 adds bounded, inspectable query expansion on top of the existing query-variant RRF path.

The original query always runs with full weight. Explicit consumer-supplied `query_variants` remain unchanged. Automatic expansion is opt-in with `expand_query=true`, is capped by `query_expansion_limit` (maximum 8), and contributes only bounded secondary RRF signal.

Two provider types are supported by the search boundary:
- deterministic `DictionaryQueryExpander` for controlled domain synonyms, abbreviations and equivalent terminology;
- `ReasoningQueryExpander`, which reuses the policy-controlled DP-MODEL-001 reasoning provider.

Model expansion is conservative: it requests only synonyms, abbreviations or domain-equivalent wording, rejects duplicates/blank/oversized output, and cannot retrieve documents itself. Provider failure or malformed output falls back to the original query.

Search responses expose every automatically generated expansion as `query_expansions` with `text`, `source` and `weight`. Expansion is therefore observable rather than hidden.

## Activation gate

Automatic expansion remains off by default. `QueryExpansionGate` compares the same frozen suite with and without expansion and requires a measurable MRR or recall@5 gain, no top-1 regression, and p95 latency <= 2x baseline.

Production acceptance v3 currently has top-1, MRR and recall@5 of 1.0, so it has no quality headroom for proving expansion value. A harder frozen suite is required before enabling expansion by default.
