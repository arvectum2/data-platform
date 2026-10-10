from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ...billing import (
    PaymentRequest,
    PriceRule,
    UsageQuantity,
    calculate_invoice,
    normalize_rules,
)

from ...storage.postgres import (
    TenantBillingAssignmentRow,
    InvoiceRow,
    InvoiceLineRow,
    BillingCatalogRow,
    UsageEventRow,
)

from ..service_support import (
    BillingCatalogNotFound,
    BillingAssignmentNotFound,
    InvoiceNotFound,
    InvoicePricingIncomplete,
)


class BillingServiceMixin:
    @staticmethod
    def _lock_tenant_billing(session: Session, tenant_id: str) -> None:
        """Serialize assignment and finalization for a tenant across workers.

        Transaction-scoped advisory locks release automatically at commit or
        rollback; unlike a process lock, these work across API instances.
        """
        session.execute(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtextextended(f"arvectum:billing:tenant:{tenant_id}", 0)
                )
            )
        )

    @staticmethod
    def _locked_invoice(session: Session, invoice_id: str) -> InvoiceRow | None:
        return session.scalar(
            select(InvoiceRow).where(InvoiceRow.invoice_id == invoice_id).with_for_update()
        )

    @staticmethod
    def _billing_catalog_payload(row: BillingCatalogRow) -> dict[str, Any]:
        return {
            "catalog_id": row.catalog_id,
            "plan_code": row.plan_code,
            "version": row.version,
            "name": row.name,
            "currency": row.currency,
            "base_fee_minor": row.base_fee_minor,
            "rules": list(row.rules_json or []),
            "status": row.status,
            "effective_from": row.effective_from,
            "created_at": row.created_at,
        }

    @staticmethod
    def _billing_assignment_payload(
        row: TenantBillingAssignmentRow,
    ) -> dict[str, Any]:
        return {
            "assignment_id": row.assignment_id,
            "tenant_id": row.tenant_id,
            "catalog_id": row.catalog_id,
            "payment_provider": row.payment_provider,
            "external_customer_id": row.external_customer_id,
            "status": row.status,
            "effective_from": row.effective_from,
            "effective_to": row.effective_to,
            "created_at": row.created_at,
        }

    @staticmethod
    def _normalize_billing_time(value: datetime, *, field: str) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        normalized = value.astimezone(UTC)
        if normalized.year < 2000 or normalized.year > 2200:
            raise ValueError(f"{field} is outside the supported range")
        return normalized

    @staticmethod
    def _billing_rule_payload(rule: PriceRule) -> dict[str, Any]:
        return {
            "operation": rule.operation,
            "unit": rule.unit,
            "unit_price_minor": rule.unit_price_minor,
            "included_quantity": rule.included_quantity,
            "description": rule.description,
        }

    def create_billing_catalog(
        self,
        *,
        plan_code: str,
        version: int,
        name: str,
        currency: str,
        base_fee_minor: int,
        rules: Sequence[Mapping[str, object]],
        effective_from: datetime,
    ) -> dict[str, Any]:
        plan_code = plan_code.strip().lower()
        name = name.strip()
        currency = currency.strip().upper()
        if not plan_code or len(plan_code) > 64:
            raise ValueError("plan_code must be between 1 and 64 characters")
        if not all(ch.isalnum() or ch in {"-", "_"} for ch in plan_code):
            raise ValueError("plan_code may contain only letters, digits, '-' and '_'")
        if version < 1:
            raise ValueError("billing catalog version must be positive")
        if not name or len(name) > 128:
            raise ValueError("billing catalog name must be between 1 and 128 characters")
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("billing currency must be a three-letter ISO-style code")
        if base_fee_minor < 0:
            raise ValueError("base_fee_minor must be non-negative")
        effective_from = self._normalize_billing_time(
            effective_from,
            field="effective_from",
        )
        normalized_rules = normalize_rules(rules)
        rules_json = [self._billing_rule_payload(rule) for rule in normalized_rules]

        with self._require_factory()() as session:
            existing = session.scalar(
                select(BillingCatalogRow).where(
                    BillingCatalogRow.plan_code == plan_code,
                    BillingCatalogRow.version == version,
                )
            )
            if existing is not None:
                raise ValueError(f"billing catalog {plan_code!r} version {version} already exists")
            row = BillingCatalogRow(
                plan_code=plan_code,
                version=version,
                name=name,
                currency=currency,
                base_fee_minor=int(base_fee_minor),
                rules_json=rules_json,
                status="active",
                effective_from=effective_from,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._billing_catalog_payload(row)

    def list_billing_catalogs(
        self,
        *,
        plan_code: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._require_factory()() as session:
            statement = select(BillingCatalogRow)
            if plan_code is not None:
                statement = statement.where(
                    BillingCatalogRow.plan_code == plan_code.strip().lower()
                )
            statement = statement.order_by(
                BillingCatalogRow.plan_code,
                BillingCatalogRow.version,
            )
            return [self._billing_catalog_payload(row) for row in session.scalars(statement)]

    def assign_tenant_billing(
        self,
        *,
        tenant_id: str,
        catalog_id: str,
        effective_from: datetime,
        payment_provider: str = "manual",
        external_customer_id: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = tenant_id.strip()
        payment_provider = payment_provider.strip().lower()
        if not tenant_id or len(tenant_id) > 128:
            raise ValueError("tenant_id must be between 1 and 128 characters")
        if payment_provider not in self.payment_providers:
            raise ValueError(f"unsupported payment provider {payment_provider!r}")
        if external_customer_id is not None and len(external_customer_id.strip()) > 256:
            raise ValueError("external_customer_id is too long")
        effective_from = self._normalize_billing_time(
            effective_from,
            field="effective_from",
        )

        with self._require_factory()() as session:
            self._lock_tenant_billing(session, tenant_id)
            catalog = session.get(BillingCatalogRow, catalog_id)
            if catalog is None:
                raise BillingCatalogNotFound(catalog_id)
            if catalog.status != "active":
                raise ValueError("billing catalog is not active")
            if catalog.effective_from > effective_from:
                raise ValueError(
                    "tenant billing assignment cannot start before catalog effective_from"
                )

            active = session.scalar(
                select(TenantBillingAssignmentRow)
                .where(
                    TenantBillingAssignmentRow.tenant_id == tenant_id,
                    TenantBillingAssignmentRow.effective_to.is_(None),
                )
                .order_by(TenantBillingAssignmentRow.effective_from.desc())
            )
            if active is not None:
                if effective_from <= active.effective_from:
                    raise ValueError(
                        "new tenant billing assignment must start after the active assignment"
                    )
                active.effective_to = effective_from
                active.status = "closed"
                session.add(active)

            row = TenantBillingAssignmentRow(
                tenant_id=tenant_id,
                catalog_id=catalog_id,
                payment_provider=payment_provider,
                external_customer_id=(
                    external_customer_id.strip() if external_customer_id is not None else None
                ),
                status="active",
                effective_from=effective_from,
                effective_to=None,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._billing_assignment_payload(row)

    def list_tenant_billing_assignments(
        self,
        *,
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        tenant_id = tenant_id.strip()
        with self._require_factory()() as session:
            statement = (
                select(TenantBillingAssignmentRow)
                .where(TenantBillingAssignmentRow.tenant_id == tenant_id)
                .order_by(TenantBillingAssignmentRow.effective_from)
            )
            return [self._billing_assignment_payload(row) for row in session.scalars(statement)]

    def _billing_assignment_for_period(
        self,
        session: Session,
        *,
        tenant_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> TenantBillingAssignmentRow:
        row = session.scalar(
            select(TenantBillingAssignmentRow)
            .where(
                TenantBillingAssignmentRow.tenant_id == tenant_id,
                TenantBillingAssignmentRow.effective_from <= period_start,
                or_(
                    TenantBillingAssignmentRow.effective_to.is_(None),
                    TenantBillingAssignmentRow.effective_to >= period_end,
                ),
            )
            .order_by(TenantBillingAssignmentRow.effective_from.desc())
        )
        if row is None:
            raise BillingAssignmentNotFound(
                f"no single billing assignment covers {tenant_id!r} for the full period"
            )
        return row

    @staticmethod
    def _invoice_line_payload(row: InvoiceLineRow) -> dict[str, Any]:
        return {
            "operation": row.operation,
            "unit": row.unit,
            "quantity": row.quantity,
            "included_quantity": row.included_quantity,
            "chargeable_quantity": row.chargeable_quantity,
            "unit_price_minor": row.unit_price_minor,
            "amount_minor": row.amount_minor,
            "description": row.description,
        }

    def _invoice_payload(
        self,
        session: Session,
        row: InvoiceRow,
        *,
        lines: Sequence[InvoiceLineRow] | None = None,
    ) -> dict[str, Any]:
        if lines is None:
            lines = list(
                session.scalars(
                    select(InvoiceLineRow)
                    .where(InvoiceLineRow.invoice_id == row.invoice_id)
                    .order_by(InvoiceLineRow.operation, InvoiceLineRow.unit)
                )
            )
        snapshot = dict(row.pricing_snapshot or {})
        return {
            "invoice_id": row.invoice_id,
            "tenant_id": row.tenant_id,
            "catalog_id": row.catalog_id,
            "period_start": row.period_start,
            "period_end": row.period_end,
            "currency": row.currency,
            "plan_code": snapshot.get("plan_code"),
            "plan_version": snapshot.get("version"),
            "base_fee_minor": int(snapshot.get("base_fee_minor") or 0),
            "subtotal_minor": row.subtotal_minor,
            "total_minor": row.total_minor,
            "status": row.status,
            "usage_snapshot_hash": row.usage_snapshot_hash,
            "pricing_snapshot": snapshot,
            "lines": [self._invoice_line_payload(line) for line in lines],
            "unpriced_usage": [],
            "payment_provider": row.payment_provider,
            "provider_reference": row.provider_reference,
            "provider_status": row.provider_status,
            "payment_url": row.payment_url,
            "created_at": row.created_at,
            "finalized_at": row.finalized_at,
            "paid_at": row.paid_at,
        }

    def _preview_invoice_in_session(
        self,
        session: Session,
        *,
        tenant_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> dict[str, Any]:
        tenant_id = tenant_id.strip()
        if not tenant_id or len(tenant_id) > 128:
            raise ValueError("tenant_id must be between 1 and 128 characters")
        period_start = self._normalize_billing_time(period_start, field="period_start")
        period_end = self._normalize_billing_time(period_end, field="period_end")
        if period_start >= period_end:
            raise ValueError("period_start must be earlier than period_end")

        assignment = self._billing_assignment_for_period(
            session,
            tenant_id=tenant_id,
            period_start=period_start,
            period_end=period_end,
        )
        catalog = session.get(BillingCatalogRow, assignment.catalog_id)
        if catalog is None:
            raise BillingCatalogNotFound(assignment.catalog_id)

        # Read only billed columns. Stream the established canonical hash
        # instead of materializing entire ORM rows (including metadata JSON)
        # and a second unbounded list of strings in memory.
        usage_statement = (
            select(
                UsageEventRow.usage_event_id,
                UsageEventRow.operation,
                UsageEventRow.unit,
                UsageEventRow.quantity,
            )
            .where(
                UsageEventRow.tenant_id == tenant_id,
                UsageEventRow.billable.is_(True),
                UsageEventRow.created_at >= period_start,
                UsageEventRow.created_at < period_end,
            )
            .order_by(UsageEventRow.usage_event_id)
            .execution_options(yield_per=1000)
        )
        usage_by_meter: dict[tuple[str, str], int] = {}
        digest = hashlib.sha256()
        first_event = True
        for row in session.execute(usage_statement):
            key = (row.operation, row.unit)
            usage_by_meter[key] = usage_by_meter.get(key, 0) + int(row.quantity)
            if not first_event:
                digest.update(b"\n")
            digest.update(
                f"{row.usage_event_id}:{row.operation}:{row.unit}:{row.quantity}".encode("utf-8")
            )
            first_event = False
        usage_snapshot_hash = digest.hexdigest()
        rules = normalize_rules(catalog.rules_json or [])
        calculation = calculate_invoice(
            base_fee_minor=int(catalog.base_fee_minor),
            rules=rules,
            usage=(
                UsageQuantity(operation=operation, unit=unit, quantity=quantity)
                for (operation, unit), quantity in usage_by_meter.items()
            ),
        )
        pricing_snapshot = {
            "plan_code": catalog.plan_code,
            "version": catalog.version,
            "name": catalog.name,
            "currency": catalog.currency,
            "base_fee_minor": catalog.base_fee_minor,
            "rules": list(catalog.rules_json or []),
        }
        return {
            "invoice_id": None,
            "tenant_id": tenant_id,
            "catalog_id": catalog.catalog_id,
            "period_start": period_start,
            "period_end": period_end,
            "currency": catalog.currency,
            "plan_code": catalog.plan_code,
            "plan_version": catalog.version,
            "base_fee_minor": calculation.base_fee_minor,
            "subtotal_minor": calculation.subtotal_minor,
            "total_minor": calculation.total_minor,
            "status": "preview",
            "usage_snapshot_hash": usage_snapshot_hash,
            "pricing_snapshot": pricing_snapshot,
            "lines": [
                {
                    "operation": line.operation,
                    "unit": line.unit,
                    "quantity": line.quantity,
                    "included_quantity": line.included_quantity,
                    "chargeable_quantity": line.chargeable_quantity,
                    "unit_price_minor": line.unit_price_minor,
                    "amount_minor": line.amount_minor,
                    "description": line.description,
                }
                for line in calculation.lines
            ],
            "unpriced_usage": [
                {
                    "operation": item.operation,
                    "unit": item.unit,
                    "quantity": item.quantity,
                }
                for item in calculation.unpriced_usage
            ],
            "payment_provider": assignment.payment_provider,
            "provider_reference": None,
            "provider_status": None,
            "payment_url": None,
            "created_at": None,
            "finalized_at": None,
            "paid_at": None,
        }

    def preview_invoice(
        self,
        *,
        tenant_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> dict[str, Any]:
        with self._require_factory()() as session:
            return self._preview_invoice_in_session(
                session,
                tenant_id=tenant_id,
                period_start=period_start,
                period_end=period_end,
            )

    def finalize_invoice(
        self,
        *,
        tenant_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> dict[str, Any]:
        period_start = self._normalize_billing_time(period_start, field="period_start")
        period_end = self._normalize_billing_time(period_end, field="period_end")
        with self._require_factory()() as session:
            # The existence check and invoice creation must be serialized.
            # A UNIQUE constraint alone would raise a duplicate-key error to
            # a concurrent worker instead of returning the original invoice.
            self._lock_tenant_billing(session, tenant_id.strip())
            existing = session.scalar(
                select(InvoiceRow).where(
                    InvoiceRow.tenant_id == tenant_id.strip(),
                    InvoiceRow.period_start == period_start,
                    InvoiceRow.period_end == period_end,
                )
            )
            if existing is not None:
                return self._invoice_payload(session, existing)

            preview = self._preview_invoice_in_session(
                session,
                tenant_id=tenant_id,
                period_start=period_start,
                period_end=period_end,
            )
            if preview["unpriced_usage"]:
                meters = ", ".join(
                    f"{item['operation']}/{item['unit']}" for item in preview["unpriced_usage"]
                )
                raise InvoicePricingIncomplete(
                    f"cannot finalize invoice with unpriced usage: {meters}"
                )

            now = datetime.now(UTC)
            row = InvoiceRow(
                tenant_id=preview["tenant_id"],
                catalog_id=preview["catalog_id"],
                period_start=period_start,
                period_end=period_end,
                currency=preview["currency"],
                pricing_snapshot=preview["pricing_snapshot"],
                usage_snapshot_hash=preview["usage_snapshot_hash"],
                subtotal_minor=preview["subtotal_minor"],
                total_minor=preview["total_minor"],
                status="finalized",
                payment_provider=preview["payment_provider"],
                finalized_at=now,
            )
            session.add(row)
            session.flush()
            for line in preview["lines"]:
                session.add(
                    InvoiceLineRow(
                        invoice_id=row.invoice_id,
                        operation=line["operation"],
                        unit=line["unit"],
                        quantity=line["quantity"],
                        included_quantity=line["included_quantity"],
                        chargeable_quantity=line["chargeable_quantity"],
                        unit_price_minor=line["unit_price_minor"],
                        amount_minor=line["amount_minor"],
                        description=line["description"],
                    )
                )
            session.commit()
            session.refresh(row)
            return self._invoice_payload(session, row)

    def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        with self._require_factory()() as session:
            row = session.get(InvoiceRow, invoice_id)
            if row is None:
                raise InvoiceNotFound(invoice_id)
            return self._invoice_payload(session, row)

    def list_invoices(
        self,
        *,
        tenant_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if limit < 1 or limit > 500:
            raise ValueError("invoice list limit must be between 1 and 500")
        with self._require_factory()() as session:
            statement = select(InvoiceRow)
            if tenant_id:
                statement = statement.where(InvoiceRow.tenant_id == tenant_id.strip())
            if status:
                statement = statement.where(InvoiceRow.status == status.strip().lower())
            statement = statement.order_by(
                InvoiceRow.period_end.desc(),
                InvoiceRow.invoice_id.desc(),
            ).limit(limit)
            invoices = list(session.scalars(statement))
            if not invoices:
                return []
            lines_by_invoice: dict[str, list[InvoiceLineRow]] = defaultdict(list)
            for line in session.scalars(
                select(InvoiceLineRow)
                .where(InvoiceLineRow.invoice_id.in_(row.invoice_id for row in invoices))
                .order_by(
                    InvoiceLineRow.invoice_id, InvoiceLineRow.operation, InvoiceLineRow.unit
                )
            ):
                lines_by_invoice[line.invoice_id].append(line)
            return [
                self._invoice_payload(
                    session, row, lines=lines_by_invoice[row.invoice_id]
                )
                for row in invoices
            ]

    def create_invoice_payment(self, invoice_id: str) -> dict[str, Any]:
        with self._require_factory()() as session:
            # Lock the invoice before checking its status. Concurrent payment
            # handoffs/reconciliation must observe committed state, not race.
            row = self._locked_invoice(session, invoice_id)
            if row is None:
                raise InvoiceNotFound(invoice_id)
            if row.status == "paid":
                return self._invoice_payload(session, row)
            if row.provider_reference:
                return self._invoice_payload(session, row)
            provider_name = (row.payment_provider or "manual").strip().lower()
            provider = self.payment_providers.get(provider_name)
            if provider is None:
                raise ValueError(f"payment provider {provider_name!r} is not configured")
            handoff = provider.create_payment(
                PaymentRequest(
                    invoice_id=row.invoice_id,
                    tenant_id=row.tenant_id,
                    currency=row.currency,
                    amount_minor=row.total_minor,
                    description=f"Arvectum Data Platform invoice {row.invoice_id}",
                )
            )
            row.payment_provider = handoff.provider
            row.provider_reference = handoff.reference
            row.provider_status = handoff.status
            row.payment_url = handoff.payment_url
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._invoice_payload(session, row)

    def sync_invoice_payment(self, invoice_id: str) -> dict[str, Any]:
        with self._require_factory()() as session:
            # Lock the invoice before checking its status. Concurrent payment
            # handoffs/reconciliation must observe committed state, not race.
            row = self._locked_invoice(session, invoice_id)
            if row is None:
                raise InvoiceNotFound(invoice_id)
            if row.status == "paid":
                return self._invoice_payload(session, row)
            provider_name = (row.payment_provider or "").strip().lower()
            reference = (row.provider_reference or "").strip()
            if not provider_name or not reference:
                raise ValueError("invoice does not have a payment handoff to synchronize")
            provider = self.payment_providers.get(provider_name)
            if provider is None:
                raise ValueError(f"payment provider {provider_name!r} is not configured")
            provider_status = provider.get_payment(reference)
            if provider_status.reference != reference:
                raise ValueError("payment provider returned a mismatched reference")
            if provider_status.currency is not None and provider_status.currency != row.currency:
                raise ValueError("payment provider returned a mismatched currency")
            if (
                provider_status.amount_minor is not None
                and provider_status.amount_minor != row.total_minor
            ):
                raise ValueError("payment provider returned a mismatched amount")

            row.provider_status = provider_status.status
            if provider_status.paid:
                row.status = "paid"
                row.paid_at = datetime.now(UTC)
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._invoice_payload(session, row)

    def mark_invoice_paid(
        self,
        invoice_id: str,
        *,
        provider_reference: str | None = None,
    ) -> dict[str, Any]:
        with self._require_factory()() as session:
            # Lock the invoice before checking its status. Concurrent payment
            # handoffs/reconciliation must observe committed state, not race.
            row = self._locked_invoice(session, invoice_id)
            if row is None:
                raise InvoiceNotFound(invoice_id)
            if row.status != "paid":
                row.status = "paid"
                row.paid_at = datetime.now(UTC)
                if provider_reference:
                    row.provider_reference = provider_reference.strip()
                row.provider_status = "succeeded"
                session.add(row)
                session.commit()
                session.refresh(row)
            return self._invoice_payload(session, row)

    @staticmethod
    def _usage_event_payload(row: UsageEventRow) -> dict[str, Any]:
        return {
            "usage_event_id": row.usage_event_id,
            "tenant_id": row.tenant_id,
            "consumer_id": row.consumer_id,
            "operation": row.operation,
            "unit": row.unit,
            "quantity": row.quantity,
            "billable": row.billable,
            "status_code": row.status_code,
            "request_id": row.request_id,
            "metadata": dict(row.metadata_json or {}),
            "created_at": row.created_at,
        }

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
            statement = pg_insert(UsageEventRow).values(
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
            ).on_conflict_do_nothing(index_elements=(UsageEventRow.usage_event_id,))
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
