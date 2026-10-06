# Customer-managed connector credentials

DP-CRED-001 adds a tenant-scoped encrypted credential vault and a provider-neutral boundary for credential-aware connectors.

## Security boundary

- plaintext connector secrets are accepted only on create/rotate requests and are never returned by the API;
- secret payloads are encrypted before PostgreSQL persistence using Fernet authenticated encryption;
- the encryption key is derived from `ARVECTUM_DATA_CONNECTOR_CREDENTIALS_MASTER_KEY`, which is supplied only through runtime configuration and is never stored in the database;
- each ciphertext records a key version so future key rotation can be introduced without changing the credential identity model;
- credentials are owned by both tenant and consumer; another consumer cannot resolve, rotate, revoke or use them;
- revoked credentials cannot be resolved for connector execution;
- open metadata is deliberately scalar-only and rejects sensitive-looking field names such as token, password, api_key and authorization;
- connector plaintext exists only in process memory while configuring the selected connector.

The master key must be a high-entropy runtime secret of at least 32 characters. If the key is absent, credential-vault operations fail with service-unavailable semantics; ordinary public connectors and search remain unaffected.

## API

Authenticated consumers can use:

- `POST /v1/connectors/credentials` — create an encrypted connector credential;
- `GET /v1/connectors/credentials` — list only that consumer's metadata;
- `POST /v1/connectors/credentials/{id}/rotate` — atomically revoke the old credential and create a replacement;
- `POST /v1/connectors/credentials/{id}/revoke` — revoke a credential;
- `POST /v1/discover` with `credential_id` — run a credential-aware connector.

Responses contain credential ID, tenant/consumer ownership, connector name, label, status, safe metadata and timestamps. They never contain plaintext secrets or ciphertext.

## Connector contract

A connector that consumes managed credentials implements `with_credentials(secrets, metadata=...)` and returns a configured connector instance. Data Platform resolves and decrypts a credential only after verifying:

1. the caller is authenticated;
2. the credential is active;
3. consumer ownership matches;
4. tenant ownership matches;
5. the requested connector name matches the credential.

If a connector does not implement the credential-aware contract, passing a `credential_id` fails instead of silently ignoring the credential.

## Discovery and metering

`/v1/discover` remains available to the internal control plane. It also accepts consumer authentication, and consumer discovery is included in DP-METER-001 request metering. Public connectors continue to work without a credential.

## Commercial/product boundary

The vault is provider-neutral infrastructure. It does not invent authentication conventions for arbitrary websites and it does not forward generic Authorization headers to arbitrary redirect targets. Each authenticated third-party connector must explicitly define how its secret fields are applied and remains subject to the existing SSRF/redirect/rate-limit policies.

Therefore the credential vault and connector binding are complete platform capabilities, while shipping the first concrete customer-authenticated third-party connector remains a separate product backlog item.
