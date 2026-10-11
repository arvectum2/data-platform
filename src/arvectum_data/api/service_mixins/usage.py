from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert


from ...storage.postgres import (
    UsageEventRow,
)

from ..billing_payloads import (
    _usage_event_payload,
)


class UsageServiceMixin:
    _usage_event_payload = staticmethod(_usage_event_payload)

    def record_usage_event(
        self,
        *,
        consumer_id: str,
        operation: str,
        request_id: str,
        status_code: int,
        unit: str = "request",
        quantity: int = 1,
        duration_ms: int | None = None,
        request_bytes: int | None = None,
    ) -> dict[str, Any]:
        consumer_id = consumer_id.strip()
        operation = operation.strip()
        unit = unit.strip()
        request_id = request_id.strip()
        if not consumer_id or len(consumer_id) > 128:
            raise ValueError("consumer_id must be between 1 and 128 characters")
        if not operation or len(operation) > 64:
            raise ValueError("operation must be between 1 and 64 characters")
        if not unit or len(unit) > 32:
            raise ValueError("unit must be between 1 and 32 characters")
        if not request_id or len(request_id) > 128:
            raise ValueError("request_id must be between 1 and 128 characters")
        if quantity < 0:
            raise ValueError("quantity must be non-negative")
        if status_code < 100 or status_code > 599:
            raise ValueError("status_code must be a valid HTTP status")
        if duration_ms is not None and duration_ms < 0:
            raise ValueError("duration_ms must be non-negative")
        if request_bytes is not None and request_bytes < 0:
            raise ValueError("request_bytes must be non-negative")

        usage_event_id = hashlib.sha256(
            "\x00".join((consumer_id, request_id, operation, unit)).encode("utf-8")
        ).hexdigest()
        with self._require_factory()() as session:
            existing = session.get(UsageEventRow, usage_event_id)
            if existing is not None:
                return self._usage_event_payload(existing)
            tenant_id = self._consumer_tenant(consumer_id, session=session) or None
            metadata: dict[str, int] = {}
            if duration_ms is not None:
                metadata["duration_ms"] = int(duration_ms)
            if request_bytes is not None:
                metadata["request_bytes"] = int(request_bytes)
            # Two concurrent responses can record the same request ID. The
            # pre-check above is only the fast idempotent path; a PostgreSQL
            # conflict guard is required to avoid a duplicate-key 500 and
            # double-charging. Never overwrite the first recorded event.
            statement = (
                pg_insert(UsageEventRow)
                .values(
                    usage_event_id=usage_event_id,
                    tenant_id=tenant_id,
                    consumer_id=consumer_id,
                    operation=operation,
                    unit=unit,
                    quantity=int(quantity),
                    billable=200 <= status_code < 400,
                    status_code=int(status_code),
                    request_id=request_id,
                    metadata_json=metadata,
                )
                .on_conflict_do_nothing(index_elements=(UsageEventRow.usage_event_id,))
            )
            session.execute(statement)
            session.commit()
            stored = session.get(UsageEventRow, usage_event_id)
            if stored is None:
                raise RuntimeError("usage event missing after idempotent insert")
            return self._usage_event_payload(stored)

    def usage_summary(
        self,
        *,
        tenant_id: str | None = None,
        consumer_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[str, Any]:
        if since is not None and since.tzinfo is None:
            since = since.replace(tzinfo=UTC)
        if until is not None and until.tzinfo is None:
            until = until.replace(tzinfo=UTC)
        if since is not None and until is not None and since >= until:
            raise ValueError("since must be earlier than until")
        tenant_id = tenant_id.strip() if tenant_id else None
        consumer_id = consumer_id.strip() if consumer_id else None

        with self._require_factory()() as session:
            statement = select(
                UsageEventRow.tenant_id,
                UsageEventRow.consumer_id,
                UsageEventRow.operation,
                UsageEventRow.unit,
                func.count(UsageEventRow.usage_event_id).label("events"),
                func.sum(UsageEventRow.quantity).label("quantity"),
                func.sum(
                    case(
                        (UsageEventRow.billable.is_(True), UsageEventRow.quantity),
                        else_=0,
                    )
                ).label("billable_quantity"),
            )
            if tenant_id is not None:
                statement = statement.where(UsageEventRow.tenant_id == tenant_id)
            if consumer_id is not None:
                statement = statement.where(UsageEventRow.consumer_id == consumer_id)
            if since is not None:
                statement = statement.where(UsageEventRow.created_at >= since)
            if until is not None:
                statement = statement.where(UsageEventRow.created_at < until)
            statement = statement.group_by(
                UsageEventRow.tenant_id,
                UsageEventRow.consumer_id,
                UsageEventRow.operation,
                UsageEventRow.unit,
            ).order_by(
                UsageEventRow.tenant_id,
                UsageEventRow.consumer_id,
                UsageEventRow.operation,
                UsageEventRow.unit,
            )
            buckets = [
                {
                    "tenant_id": row.tenant_id,
                    "consumer_id": row.consumer_id,
                    "operation": row.operation,
                    "unit": row.unit,
                    "events": int(row.events or 0),
                    "quantity": int(row.quantity or 0),
                    "billable_quantity": int(row.billable_quantity or 0),
                }
                for row in session.execute(statement)
            ]

        return {
            "since": since,
            "until": until,
            "total_events": sum(item["events"] for item in buckets),
            "total_quantity": sum(item["quantity"] for item in buckets),
            "billable_quantity": sum(item["billable_quantity"] for item in buckets),
            "buckets": buckets,
        }
