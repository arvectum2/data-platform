"""Opt-in durable PostgreSQL job intake and lease-based document ingest worker.

The 202 acknowledgement is a COMMITTED queue receipt, never a search-ready claim.
Workers are launched separately and deliberately disabled in production by default.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import load_only

from ..storage.postgres import AsyncIngestJobRow, CollectionRow
from ..supportability import percentile

ACTIVE = ("queued", "running")
TERMINAL = ("completed", "dead_letter", "cancelled")


class IngestFeatureDisabled(RuntimeError):
    pass


class IngestJobConflict(ValueError):
    pass


class IngestJobQueueFull(RuntimeError):
    pass


class IngestJobNotFound(LookupError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _receipt(row: AsyncIngestJobRow) -> dict[str, Any]:
    # No bytes, text, filenames, external URIs, secret idempotency keys or exception details.
    safe_result = None
    if row.status == "completed" and row.result_json:
        safe_result = {
            key: row.result_json[key]
            for key in ("resource_id", "document_id", "chunks", "embeddings_written")
            if key in row.result_json
        }
    return {
        "job_id": row.job_id,
        "collection_id": row.collection_id,
        "status": row.status,
        "attempts": row.attempts,
        "created_at": row.created_at,
        "completed_at": row.completed_at,
        "result": safe_result,
    }


def _fingerprint(
    *,
    content: bytes,
    collection_id: str,
    filename: str,
    canonical_uri: str | None,
    title: str | None,
    pre_chunked: bool,
) -> str:
    fields = json.dumps(
        [
            collection_id,
            filename,
            canonical_uri,
            title,
            pre_chunked,
            hashlib.sha256(content).hexdigest(),
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(fields.encode()).hexdigest()


def _lock_collection(session: Any, collection_id: str) -> None:
    # Serializes admission/bytes quota and idempotency within each collection.
    digest = hashlib.sha256(collection_id.encode()).digest()
    key = int.from_bytes(digest[:8], byteorder="big", signed=True)
    session.execute(select(func.pg_advisory_xact_lock(key)))


class AsyncIngestServiceMixin:
    def enqueue_ingest_document(
        self,
        *,
        collection_id: str,
        filename: str,
        content: bytes,
        idempotency_key: str,
        canonical_uri: str | None = None,
        title: str | None = None,
        pre_chunked: bool = False,
    ) -> dict[str, Any]:
        if not self.settings.async_ingest_enabled:
            raise IngestFeatureDisabled("asynchronous document ingest is not enabled")
        if not (1 <= len(content) <= self.settings.max_upload_bytes):
            raise ValueError("upload size outside supported limit")
        if len(content) > self.settings.async_ingest_max_bytes:
            raise ValueError("async upload exceeds configured maximum size")
        if not (1 <= len(filename) <= 256 and 1 <= len(collection_id) <= 128):
            raise ValueError("invalid job source or collection")
        if title is not None and len(title) > 1024:
            raise ValueError("title exceeds maximum length")
        if canonical_uri is not None and len(canonical_uri) > 4096:
            raise ValueError("canonical URI exceeds maximum length")
        if not (8 <= len(idempotency_key) <= 128) or not re.fullmatch(
            r"[a-zA-Z0-9_.:-]+", idempotency_key
        ):
            raise ValueError("idempotency key must be 8..128 safe characters")
        key_digest = hashlib.sha256(idempotency_key.encode()).hexdigest()
        request_digest = _fingerprint(
            content=content,
            collection_id=collection_id,
            filename=filename,
            canonical_uri=canonical_uri,
            title=title,
            pre_chunked=pre_chunked,
        )
        with self._require_factory()() as session:
            # A shared first lock caps aggregate queued byte storage across
            # collections; second lock scopes idempotency and collection quotas.
            _lock_collection(session, "__dp_async_ingest_global_admission__")
            _lock_collection(session, collection_id)
            if session.get(CollectionRow, collection_id) is None:
                raise IngestJobNotFound("collection unavailable")
            existing = session.scalar(
                select(AsyncIngestJobRow)
                .where(
                    AsyncIngestJobRow.collection_id == collection_id,
                    AsyncIngestJobRow.idempotency_digest == key_digest,
                )
                .options(
                    load_only(
                        AsyncIngestJobRow.job_id,
                        AsyncIngestJobRow.status,
                        AsyncIngestJobRow.request_digest,
                        AsyncIngestJobRow.attempts,
                        AsyncIngestJobRow.created_at,
                        AsyncIngestJobRow.completed_at,
                        AsyncIngestJobRow.result_json,
                    )
                )
            )
            if existing is not None:
                if existing.request_digest != request_digest:
                    raise IngestJobConflict("idempotency key reused for a different request")
                return _receipt(existing)
            queued_n, queued_bytes = session.execute(
                select(
                    func.count(), func.coalesce(func.sum(AsyncIngestJobRow.input_bytes), 0)
                ).where(
                    AsyncIngestJobRow.collection_id == collection_id,
                    AsyncIngestJobRow.status.in_(ACTIVE),
                )
            ).one()
            if (
                queued_n >= self.settings.async_ingest_max_active_jobs
                or queued_bytes + len(content) > self.settings.async_ingest_max_queued_bytes
            ):
                raise IngestJobQueueFull("async ingest queue capacity exceeded")
            global_jobs, global_bytes = session.execute(
                select(
                    func.count(), func.coalesce(func.sum(AsyncIngestJobRow.input_bytes), 0)
                ).where(AsyncIngestJobRow.status.in_(ACTIVE))
            ).one()
            if (
                global_jobs >= self.settings.async_ingest_max_global_jobs
                or global_bytes + len(content) > self.settings.async_ingest_max_global_queued_bytes
            ):
                raise IngestJobQueueFull("global async ingest queue capacity exceeded")
            row = AsyncIngestJobRow(
                job_id=str(uuid.uuid4()),
                collection_id=collection_id,
                idempotency_digest=key_digest,
                request_digest=request_digest,
                filename=filename,
                canonical_uri=canonical_uri,
                title=title,
                pre_chunked=pre_chunked,
                content=content,
                input_bytes=len(content),
                status="queued",
                attempts=0,
            )
            session.add(row)
            session.commit()  # After this point, POST 202 is truthful across restarts.
            session.refresh(row)
            return _receipt(row)

    def get_ingest_job(self, *, collection_id: str, job_id: str) -> dict[str, Any]:
        if not self.settings.async_ingest_enabled:
            raise IngestFeatureDisabled("asynchronous document ingest is not enabled")
        with self._require_factory()() as session:
            row = session.scalar(
                select(AsyncIngestJobRow)
                .where(
                    AsyncIngestJobRow.collection_id == collection_id,
                    AsyncIngestJobRow.job_id == job_id,
                )
                .options(
                    load_only(
                        AsyncIngestJobRow.job_id,
                        AsyncIngestJobRow.collection_id,
                        AsyncIngestJobRow.status,
                        AsyncIngestJobRow.attempts,
                        AsyncIngestJobRow.created_at,
                        AsyncIngestJobRow.completed_at,
                        AsyncIngestJobRow.result_json,
                    )
                )
            )
            if row is None:
                raise IngestJobNotFound("job unavailable")
            return _receipt(row)

    def async_ingest_readiness(self) -> dict[str, Any]:
        """Separate aggregate-only metrics for durable background ingestion."""
        if not self.settings.async_ingest_enabled:
            return {"status": "disabled", "scope": "async_ingest_only"}
        now = _now()
        with self._require_factory()() as session:
            backlog_count, backlog_bytes, oldest = session.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(AsyncIngestJobRow.input_bytes), 0),
                    func.min(AsyncIngestJobRow.created_at),
                ).where(AsyncIngestJobRow.status.in_(ACTIVE))
            ).one()
            rows = list(
                session.scalars(
                    select(AsyncIngestJobRow)
                    .order_by(AsyncIngestJobRow.created_at.desc(), AsyncIngestJobRow.job_id.desc())
                    .limit(256)
                    .options(
                        load_only(
                            AsyncIngestJobRow.job_id,
                            AsyncIngestJobRow.status,
                            AsyncIngestJobRow.created_at,
                            AsyncIngestJobRow.started_at,
                            AsyncIngestJobRow.completed_at,
                        )
                    )
                )
            )
        queue_durations = [
            max(0, int((row.started_at - row.created_at).total_seconds() * 1000))
            for row in rows
            if row.started_at is not None
        ]
        success_durations = [
            max(0, int((row.completed_at - row.created_at).total_seconds() * 1000))
            for row in rows
            if row.status == "completed" and row.completed_at is not None
        ]
        terminal = sum(row.status in ("completed", "dead_letter") for row in rows)
        dead = sum(row.status == "dead_letter" for row in rows)
        return {
            "status": "diagnostic_only_no_slo_assigned",
            "scope": "recent_256_by_enqueue_time",
            "samples": len(rows),
            "backlog_active_count_global": int(backlog_count),
            "backlog_active_bytes_global": int(backlog_bytes),
            "backlog_oldest_age_ms_global": (
                max(0, int((now - oldest).total_seconds() * 1000)) if oldest is not None else 0
            ),
            "started_samples": len(queue_durations),
            "sufficient_queue_samples": len(queue_durations) >= 20,
            "queue_wait_p95_ms": percentile(queue_durations, 0.95),
            "completed_samples": len(success_durations),
            "sufficient_completion_samples": len(success_durations) >= 20,
            "completed_p95_ms": percentile(success_durations, 0.95),
            "terminal_samples": terminal,
            "terminal_dead_letter_count": dead,
            "terminal_error_rate": round(dead / terminal, 6) if terminal else None,
            "note": (
                "Completion is measured from durable enqueue to committed searchable index. "
                "No background completion target is yet approved; 202 is not completion."
            ),
        }

    def cancel_queued_ingest_job(self, *, collection_id: str, job_id: str) -> dict[str, Any]:
        if not self.settings.async_ingest_enabled:
            raise IngestFeatureDisabled("asynchronous document ingest is not enabled")
        with self._require_factory()() as session:
            row = session.scalar(
                select(AsyncIngestJobRow)
                .where(
                    AsyncIngestJobRow.collection_id == collection_id,
                    AsyncIngestJobRow.job_id == job_id,
                )
                .with_for_update()
            )
            if row is None:
                raise IngestJobNotFound("job unavailable")
            if row.status == "queued":
                row.status = "cancelled"
                row.content = None
                row.completed_at = _now()
                session.commit()
            elif row.status not in TERMINAL:
                raise IngestJobConflict("running jobs cannot be cancelled safely")
            return _receipt(row)
