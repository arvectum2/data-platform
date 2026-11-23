# Arvectum Data Platform Consumer SDK 0.4.1

This is an additive backward-compatible Python consumer SDK release.
It preserves SDK HTTP contract 1.x and the existing sync APIs.

New opt-in durable ingestion methods:
- enqueue_ingest_document_bytes (only valid HTTP 202 is accepted);
- get_ingest_job (status and readiness);
- cancel_queued_ingest_job (queued-only cancellation);
- async_ingest_metrics (status, not content);

This does not enable asynchronous ingestion by default in the Data Platform
service or Tender Agent. Consumer code must not treat 202 as a searchable
document. Partial/UNKNOWN results require reconciliation, never implicit
completion or blind resubmission.

Release evidence must include exact source commit SHA, wheel SHA-256,
SDK tests and cross-repository disposable PostgreSQL/HTTP acceptance.
Never overwrite the existing immutable 0.4.0 release artifact.
