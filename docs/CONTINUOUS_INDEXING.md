# Continuous indexing

DP-SYNC-001 adds refresh state to existing URL resources rather than creating a second ingestion system.

Each URL resource can have a bounded refresh policy: interval, failure threshold and enabled state. `POST /v1/sync/refresh-due` is the worker-facing entry point; an external scheduler may call it at any cadence, while each resource's `next_refresh_at` determines whether work is actually due.

Refresh acquires and extracts the source through the existing safe acquisition pipeline. ETag and Last-Modified values are retained when servers expose them, while SHA-256 content hash is the authoritative change detector across all sources.

If the content hash is unchanged, only freshness state and HTTP validators are updated; chunking and embedding are skipped. If the hash changes, the normal immutable document/chunk ingestion path runs and only previously unseen chunks receive embeddings.

Failures never destroy the last known evidence. A resource becomes `refresh_error` first and `stale` after its configured consecutive-failure threshold. Every attempt is recorded in `dp_refresh_runs` with timestamps, outcome, old/new hash and non-sensitive diagnostic metadata.

Endpoints:
- `PUT /v1/resources/{resource_id}/refresh-policy`
- `POST /v1/resources/{resource_id}/refresh`
- `POST /v1/sync/refresh-due`
- `GET /v1/resources/{resource_id}/refresh-runs`

The platform deliberately does not embed a daemon scheduler into the API process. Production can trigger the due-work endpoint from systemd/cron/Arvectum orchestration without coupling scheduling lifecycle to HTTP serving.
