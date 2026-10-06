# Deployment and privacy modes

Data Platform has two deployment modes.

## standard

standard is the compatibility/default mode. Database, embedding, reasoning and
vision endpoints follow their normal individual configuration. Reasoning and
vision still use the existing per-role policy boundary:

- disabled;
- local-only;
- remote-allowlist.

Remote model providers are never selected implicitly. A remote reasoning or
vision endpoint requires the corresponding remote-allowlist policy and an
allowed hostname.

## local-private

local-private is a startup invariant for customer-controlled processing. The
service refuses to start when the configured core path can send documents or
model requests outside the local host.

The mode requires:

- API bind address on loopback;
- database on loopback/local SQLite when configured;
- embeddings in-process or through a loopback endpoint;
- OCR disabled or local Tesseract;
- reasoning disabled or local-only on a loopback endpoint;
- vision disabled or local-only on a loopback endpoint;
- empty reasoning and vision remote allowlists.

Cross-encoder reranking is local in-process inference and does not send
candidate text to a remote provider.

External discovery/acquisition connectors are intentionally outside this
guarantee: they can fetch source material from configured external websites.
The guarantee covers the stored document/model-processing core after source
acquisition.

GET /v1/status exposes deployment_mode so consumers and support tooling can
verify the active policy.

## Fail-fast behavior

Privacy mode validation happens during Settings construction before the service
starts. A remote database, remote embedding endpoint, remote model policy, stale
remote allowlist or non-loopback API bind causes local-private configuration to
fail closed rather than silently falling back to standard mode.
