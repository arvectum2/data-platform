"""Explicitly launched, bounded PostgreSQL-backed asynchronous ingest worker.

No production launcher is registered. Can be invoked only when the async
feature flag is set; never changes the existing synchronous HTTP path.
"""

from __future__ import annotations

import argparse
import threading
import time
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update

from ..storage.postgres import AsyncIngestJobRow
from .async_ingest import _now
from .config import Settings
from .service import DataPlatformService


def claim_one(service: DataPlatformService) -> dict[str, Any] | None:
    if not service.settings.async_ingest_enabled:
        raise RuntimeError("async ingest worker disabled")
    now = _now()
    with service._require_factory()() as session:
        row = session.scalar(
            select(AsyncIngestJobRow)
            .where(
                or_(
                    and_(
                        AsyncIngestJobRow.status == "queued",
                        or_(
                            AsyncIngestJobRow.run_after.is_(None),
                            AsyncIngestJobRow.run_after <= now,
                        ),
                    ),
                    and_(
                        AsyncIngestJobRow.status == "running",
                        AsyncIngestJobRow.lease_expires_at < now,
                    ),
                )
            )
            .order_by(AsyncIngestJobRow.created_at, AsyncIngestJobRow.job_id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return None
        if row.attempts >= service.settings.async_ingest_max_attempts or row.content is None:
            row.status = "dead_letter"
            row.content = None
            row.error_class = "attempts_exhausted_or_payload_missing"
            row.completed_at = now
            row.lease_token = None
            row.lease_expires_at = None
            session.commit()
            return {"job_id": row.job_id, "skipped": True}
        token = str(uuid.uuid4())
        row.status = "running"
        row.attempts += 1
        row.lease_token = token
        row.lease_expires_at = now + timedelta(seconds=service.settings.async_ingest_lease_seconds)
        if row.started_at is None:
            row.started_at = now  # Stable first-start queue wait across bounded retries.
        row.updated_at = now
        session.commit()
        # Bytes live only until completed/dead-letter/cancelled (not returned in API).
        return {
            "job_id": row.job_id,
            "lease_token": token,
            "collection_id": row.collection_id,
            "filename": row.filename,
            "canonical_uri": row.canonical_uri or f"async-upload://{row.job_id}/{row.filename}",
            "title": row.title,
            "pre_chunked": row.pre_chunked,
            "content": bytes(row.content),
            "attempts": row.attempts,
        }


def _heartbeat(
    service: DataPlatformService, job_id: str, token: str, stop: threading.Event
) -> None:
    while not stop.wait(service.settings.async_ingest_heartbeat_seconds):
        try:
            with service._require_factory()() as session:
                session.execute(
                    update(AsyncIngestJobRow)
                    .where(
                        AsyncIngestJobRow.job_id == job_id,
                        AsyncIngestJobRow.lease_token == token,
                        AsyncIngestJobRow.status == "running",
                    )
                    .values(
                        lease_expires_at=_now()
                        + timedelta(seconds=service.settings.async_ingest_lease_seconds),
                        updated_at=_now(),
                    )
                )
                session.commit()
        except Exception:
            # Worker result is still guarded by lease-token match; failed
            # heartbeat eventually makes the job re-claimable after expiry.
            pass


def complete_one(
    service: DataPlatformService,
    claim: dict[str, Any],
    *,
    result: dict[str, Any] | None = None,
    failure: BaseException | None = None,
) -> None:
    if claim.get("skipped"):
        return
    job_id, token = claim["job_id"], claim["lease_token"]
    now = _now()
    with service._require_factory()() as session:
        row = session.scalar(
            select(AsyncIngestJobRow)
            .where(
                AsyncIngestJobRow.job_id == job_id,
                AsyncIngestJobRow.lease_token == token,
                AsyncIngestJobRow.status == "running",
            )
            .with_for_update()
        )
        if row is None:
            # Lease was superseded. No stale worker can overwrite newer status.
            return
        row.lease_token = None
        row.lease_expires_at = None
        row.updated_at = now
        if failure is None:
            if result is None:
                raise RuntimeError("worker completion requires a committed result")
            row.status = "completed"
            row.result_json = {
                key: result[key]
                for key in ("resource_id", "document_id", "chunks", "embeddings_written")
                if key in result
            }
            row.content = None
            row.error_class = None
            row.completed_at = now
        else:
            row.error_class = type(failure).__name__[:96]
            # Invalid requests/configuration cannot succeed on retry.
            invalid = isinstance(failure, (ValueError, PermissionError))
            if invalid or row.attempts >= service.settings.async_ingest_max_attempts:
                row.status = "dead_letter"
                row.content = None
                row.completed_at = now
            else:
                row.status = "queued"
                row.run_after = now + timedelta(seconds=min(15 * (2 ** (row.attempts - 1)), 300))
        session.commit()


def run_one(service: DataPlatformService) -> bool:
    claim = claim_one(service)
    if claim is None:
        return False
    if claim.get("skipped"):
        return True
    stop = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat,
        args=(service, claim["job_id"], claim["lease_token"], stop),
        name="dp-async-ingest-heartbeat",
        daemon=True,
    )
    heartbeat.start()
    try:
        try:
            result = service.ingest_document_bytes(
                collection_id=claim["collection_id"],
                filename=claim["filename"],
                content=claim["content"],
                canonical_uri=claim["canonical_uri"],
                title=claim["title"],
                pre_chunked=claim["pre_chunked"],
            )
        except Exception as exc:
            complete_one(service, claim, failure=exc)
        else:
            # Ingest has committed. A crash before status commit is safe to
            # retry: deterministic document IDs + skip-existing embeddings.
            complete_one(service, claim, result=result)
    finally:
        stop.set()
        heartbeat.join(timeout=2)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--allow-worker", action="store_true")
    args = parser.parse_args()
    if not args.allow_worker or args.once == args.loop:
        parser.error("explicit --allow-worker and exactly one of --once/--loop required")
    settings = Settings()
    if not settings.async_ingest_enabled or not settings.database_url:
        parser.error("durable ingest requires opt-in enable flag and database")
    service = DataPlatformService(settings)
    if args.once:
        run_one(service)
    else:
        while True:
            if not run_one(service):
                time.sleep(2)


if __name__ == "__main__":
    main()
