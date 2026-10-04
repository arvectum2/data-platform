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

### Retrieval parity follow-up

An isolated current-state legacy baseline was rebuilt from the same 60 Tender Agent chunks with the same Qwen3-Embedding-4B provider. The first equal-weight hybrid profile matched legacy top-1 on four of five representative procurement questions. The mismatch was caused by a weak lexical singleton outranking the semantic top hit through equal-weight RRF.

Data Platform now supports generic per-request RRF weights while preserving 1:1 as the platform default. Tender Agent uses the product-specific semantic-first profile lexical_weight=1 and vector_weight=4. After this change, production top-1 matched the isolated legacy semantic baseline on all five questions. The five Data Platform queries averaged about 0.159 s; a retrieval-only fast analysis completed ten sections with sixteen unique sources in about 1.44 s, with no warnings or errors.

## Rollback

Application rollback is explicit:

```text
AI_CORP_RAG_RETRIEVAL_BACKEND=legacy
```

Do not silently fall back from Data Platform to legacy retrieval.

Before using legacy as a production rollback, validate its vector-store path and data freshness. At the first Data Platform rollout, the configured legacy vector-store path referenced an unavailable historical volume; located archive copies were pre-2026-08-01 and are not a valid current parity baseline.

## Capacity and retry defaults

Production uses the Data Platform defaults unless explicitly overridden:

    ARVECTUM_DATA_MAX_UPLOAD_BYTES=10000000
    ARVECTUM_DATA_MAX_CHUNKS_PER_INGEST=1000
    ARVECTUM_DATA_MAX_SEARCH_COLLECTIONS=32
    ARVECTUM_DATA_EMBEDDING_RETRY_MAX_ATTEMPTS=3
    ARVECTUM_DATA_EMBEDDING_RETRY_BASE_DELAY_SECONDS=0.25
    ARVECTUM_DATA_EMBEDDING_RETRY_MAX_DELAY_SECONDS=2.0

Transient embedding-server unavailability is retried with bounded exponential backoff. Durable reindex jobs move to dead_letter after the final transient failure and preserve the previous active index revision. Re-running the same revision reuses the durable job instead of creating a duplicate. Permanent contract/schema failures are marked failed and are not blindly retried.

## Backup and restore

Canonical helpers live in scripts/ops/backup-postgres.sh and scripts/ops/restore-postgres.sh. Backups use PostgreSQL custom format, write a SHA-256 sidecar and JSON manifest, and default to file mode 0600.

Example backup:

    scripts/ops/backup-postgres.sh --output-dir /Volumes/ArvectumSSD/Arvectum/runtime/data-platform-backups

Restore requires an explicit target database. The helper refuses to restore into arvectum_data unless --allow-production-target is passed deliberately. Normal acceptance and recovery drills should restore into a separate temporary database first.

The 2026-10-04 production acceptance backed up the live arvectum_data database and restored it into arvectum_data_restore_test. Source and restored counts matched exactly: 7 collections, 155 resources, 155 documents, 432 chunks, 432 embeddings and 0 pipeline runs. The backup checksum matched before restore and the temporary restore database was removed after verification.

## Operational notes

During rollout, the Tender runtime also revealed a stale PostgreSQL password in its local `.env.local`. The runtime database URL was synchronized to the active PostgreSQL container and verified with a fresh SQL `SELECT 1` before production acceptance.

This credential repair is a Tender runtime operational issue, not a Data Platform schema or API change.
## Federated search acceptance

Consumer-scoped federation was enabled in production on 2026-10-04. The runtime stores the Growth consumer key outside Git with file mode 0600 and exports it into `ARVECTUM_DATA_CONSUMER_API_KEYS` only at service startup.

Acceptance used the active site and product collections together:

```text
growth:arvectum-site:8f0e23f96d45b1b9
growth:products:e93c4eb90b2b2e3a
```

Observed behavior for query `Фото под размер`:

```text
no consumer identity -> HTTP 403
invalid consumer key -> HTTP 403
valid growth-agent key -> HTTP 200
hits returned from both requested collections
```

Federated authorization is fail-closed. The service never silently removes an unauthorized collection from the request.

