# Mac mini runtime

This document records the first production runtime contour for Arvectum Data Platform.

## Service identity

- launchd label: `com.arvectum.data-platform`
- bind address: `127.0.0.1:8094`
- runtime checkout: `/Users/master/arvectum-runtime/data-platform`
- canonical source repository: `/Volumes/ArvectumSSD/Arvectum/repos/data-platform`
- PostgreSQL database: `arvectum_data`
- PostgreSQL runtime: existing `arvectum-postgres` pgvector container on host port `55432`
- embedding provider: `llama_cpp`
- embedding model: `Qwen3-Embedding-4B`
- embedding endpoint: `http://127.0.0.1:8090/v1`
- embedding dimension: `2560`

Data Platform is localhost-only. It does not expose the service directly to the LAN or public internet.

## Runtime boundary

Data Platform owns reusable indexing and retrieval. Tender Agent remains the canonical owner of procurement-domain chunks and citations.

Tender Agent currently uses:

```text
AI_CORP_RAG_RETRIEVAL_BACKEND=data_platform
AI_CORP_RAG_DATA_PLATFORM_BASE_URL=http://127.0.0.1:8094
```

The integration uses pre-chunked ingestion, so Data Platform indexes Tender Agent chunks as supplied and does not re-chunk procurement content.

## Startup

The launch agent lives at:

```text
~/Library/LaunchAgents/com.arvectum.data-platform.plist
```

The runtime wrapper is:

```text
/Users/master/arvectum-runtime/data-platform/run-server.sh
```

The wrapper derives PostgreSQL credentials from the already-running `arvectum-postgres` container at runtime and selects the dedicated `arvectum_data` database. Credentials are not committed to the repository.

## Health checks

```bash
curl -fsS http://127.0.0.1:8094/health
curl -fsS http://127.0.0.1:8094/v1/status
launchctl list | grep com.arvectum.data-platform
lsof -nP -iTCP:8094 -sTCP:LISTEN
```

Expected status includes:

```text
environment=production
database_configured=true
embedding_provider=llama_cpp
embedding_model=Qwen3-Embedding-4B
embedding_dimension=2560
```

## Restart

```bash
launchctl kickstart -k gui/$(id -u)/com.arvectum.data-platform
```

After restart, verify `/health` before restarting or switching any consumer.

## Migrations

Run migrations from the runtime checkout with the runtime environment loaded before service startup.

The production database is deliberately separate from the Tender Agent `arvectum` database. Do not install Data Platform tables into the Tender Agent schema.

## First Tender Agent acceptance

Production acceptance on 2026-10-04 used registry number `0187200001726001304`.

Observed acceptance state:

```text
resources=60
documents=60
chunks=60
embeddings=60
ready_for_analysis=true
retrieval_provider=data_platform
retrieval_model=hybrid
```

A live hybrid retrieval returned five mapped Tender Agent chunks in roughly 0.32 s. Retrieval-only fast analysis completed ten sections with sixteen unique sources in roughly 1.5 s with no warnings or errors.

These timings are acceptance observations, not an SLA.

## Rollback

Application rollback is explicit:

```text
AI_CORP_RAG_RETRIEVAL_BACKEND=legacy
```

Do not silently fall back from Data Platform to legacy retrieval.

Before using legacy as a production rollback, validate its vector-store path and data freshness. At the first Data Platform rollout, the configured legacy vector-store path referenced an unavailable historical volume; located archive copies were pre-2026-08-01 and are not a valid current parity baseline.

## Operational notes

During rollout, the Tender runtime also revealed a stale PostgreSQL password in its local `.env.local`. The runtime database URL was synchronized to the active PostgreSQL container and verified with a fresh SQL `SELECT 1` before production acceptance.

This credential repair is a Tender runtime operational issue, not a Data Platform schema or API change.
