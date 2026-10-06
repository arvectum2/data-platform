# External consumer authentication and key lifecycle

Data Platform supports two consumer-key sources:

- bootstrap/static keys configured through consumer_api_keys;
- managed database-backed keys issued through the internal control plane.

Static keys remain backward-compatible and are checked first. A valid static key
does not query the managed-key table, which permits rolling database migrations.

## Managed keys

Internal administrators can use:

- POST /v1/auth/consumer-keys to issue a key;
- GET /v1/auth/consumer-keys to list metadata, optionally filtered by consumer_id;
- POST /v1/auth/consumer-keys/{key_id}/rotate to atomically revoke and replace an active key;
- POST /v1/auth/consumer-keys/{key_id}/revoke to revoke a key.

The server generates an avk_ prefixed high-entropy secret. Plaintext is returned
only by create/rotate. PostgreSQL stores only SHA-256 of the generated random
secret plus a short display prefix, consumer/tenant identity, status, label and
optional expiry.

List/revoke responses never contain the plaintext secret.

## External data-plane access

A valid consumer key can authenticate consumer-facing data-plane routes without
the internal control-plane key:

- /v1/search;
- /v1/answer;
- /v1/research;
- /v1/memory and memory deletion.

Admin/control-plane endpoints remain protected by X-Arvectum-Key. A consumer
key cannot list collections, issue keys, change retention, inspect support
state or perform other control-plane operations.

Collection tenant policy and tenant quotas are evaluated after authentication.
For a managed key, tenant_id is resolved from the active key record, so an
external consumer does not require a duplicate consumer_tenants environment
mapping.

## Rotation and revocation

Rotation is allowed only for an active, non-expired key. The old key is revoked
and the replacement is committed in the same database transaction. Requests
using the old secret fail immediately after commit.

Revocation is idempotent. Expired or revoked keys cannot authenticate.

Managed-key authentication never falls back to another consumer identity and
does not broaden collection permissions.
