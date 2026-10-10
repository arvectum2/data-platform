"""Cross-session billing races against a disposable real PostgreSQL database."""
from __future__ import annotations

import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

from arvectum_data.api.config import Settings
from arvectum_data.api.service import DataPlatformService
from arvectum_data.billing import PaymentHandoff, PaymentStatus
from arvectum_data.storage.postgres import InvoiceLineRow, InvoiceRow, TenantBillingAssignmentRow

pytestmark = pytest.mark.postgres


def _service(*, payment_providers=None):
    url = os.getenv("ARVECTUM_DATA_TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("ARVECTUM_DATA_TEST_DATABASE_URL is not configured")
    os.environ["ARVECTUM_DATA_DATABASE_URL"] = url
    command.upgrade(Config("alembic.ini"), "head")
    return DataPlatformService(Settings(
        environment="test", database_url=url, embedding_provider="hashing",
        embedding_model="concurrent-billing", embedding_dimension=16,
    ), payment_providers=payment_providers)


def _setup(service, *, payment_provider="manual"):
    suffix = uuid.uuid4().hex[:12]
    tenant = f"concurrent-billing-{suffix}"
    consumer = f"concurrent-meter-{suffix}"
    now = datetime.now(UTC)
    service.create_consumer_key(consumer_id=consumer, tenant_id=tenant, label="concurrency")
    catalog = service.create_billing_catalog(
        plan_code=f"concurrent-{suffix}", version=1, name="Concurrent",
        currency="RUB", base_fee_minor=300,
        rules=({"operation": "search", "unit": "request", "unit_price_minor": 11},),
        effective_from=now - timedelta(days=3),
    )
    service.assign_tenant_billing(
        tenant_id=tenant, catalog_id=catalog["catalog_id"],
        effective_from=now - timedelta(days=2), payment_provider=payment_provider,
    )
    for i in range(3):
        service.record_usage_event(
            consumer_id=consumer, operation="search", status_code=200,
            request_id=f"{suffix}-{i}",
        )
    return tenant, catalog["catalog_id"], now


def test_concurrent_invoice_finalization_has_exactly_one_immutable_invoice():
    service = _service()
    tenant, _, now = _setup(service)
    start = now - timedelta(hours=2)
    end = now + timedelta(hours=2)
    gate = threading.Barrier(8)

    def finalize(_):
        gate.wait(timeout=8)
        return service.finalize_invoice(
            tenant_id=tenant, period_start=start, period_end=end,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        invoices = list(pool.map(finalize, range(8)))
    assert len({row["invoice_id"] for row in invoices}) == 1
    assert len({row["usage_snapshot_hash"] for row in invoices}) == 1
    assert all(row["total_minor"] == 333 and len(row["lines"]) == 1 for row in invoices)
    with service.session_factory() as session:
        count = session.scalar(select(func.count()).select_from(InvoiceRow).where(
            InvoiceRow.tenant_id == tenant,
            InvoiceRow.period_start == start,
            InvoiceRow.period_end == end,
        ))
        lines = session.scalar(select(func.count()).select_from(InvoiceLineRow).where(
            InvoiceLineRow.invoice_id == invoices[0]["invoice_id"]
        ))
    assert count == 1 and lines == 1


class _DelayedPaymentProvider:
    name = "fake-concurrent"

    def __init__(self):
        self.calls = 0
        self.lock = threading.Lock()

    def create_payment(self, request):
        with self.lock:
            self.calls += 1
        time.sleep(0.08)
        return PaymentHandoff(
            provider=self.name, status="pending", reference=f"payment:{request.invoice_id}",
            payment_url="https://pay.example.test/payment",
        )

    def get_payment(self, reference):
        return PaymentStatus(
            provider=self.name, status="succeeded", reference=reference, paid=True,
            currency="RUB", amount_minor=333,
        )


def test_concurrent_payment_handoff_calls_provider_exactly_once():
    provider = _DelayedPaymentProvider()
    service = _service(payment_providers={provider.name: provider})
    tenant, _, now = _setup(service, payment_provider=provider.name)
    invoice = service.finalize_invoice(
        tenant_id=tenant, period_start=now - timedelta(hours=2),
        period_end=now + timedelta(hours=2),
    )
    gate = threading.Barrier(6)

    def handoff(_):
        gate.wait(timeout=8)
        return service.create_invoice_payment(invoice["invoice_id"])

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(handoff, range(6)))
    assert provider.calls == 1
    assert {row["provider_reference"] for row in results} == {
        f"payment:{invoice['invoice_id']}"
    }
    assert all(row["status"] == "finalized" for row in results)
    synchronized = service.sync_invoice_payment(invoice["invoice_id"])
    assert synchronized["status"] == "paid"
    assert synchronized["paid_at"] is not None
    original_paid_at = synchronized["paid_at"]
    replay = service.create_invoice_payment(invoice["invoice_id"])
    assert replay["paid_at"] == original_paid_at
    assert provider.calls == 1


def test_simultaneous_billing_assignments_cannot_leave_two_active_rows():
    service = _service()
    tenant, catalog_id, now = _setup(service)
    effective = now + timedelta(hours=1)
    gate = threading.Barrier(2)

    def assign(_):
        gate.wait(timeout=8)
        try:
            return service.assign_tenant_billing(
                tenant_id=tenant, catalog_id=catalog_id, effective_from=effective,
            )
        except ValueError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(assign, range(2)))
    assert sum(isinstance(row, dict) for row in results) == 1
    assert sum(isinstance(row, ValueError) for row in results) == 1
    with service.session_factory() as session:
        active = list(session.scalars(select(TenantBillingAssignmentRow).where(
            TenantBillingAssignmentRow.tenant_id == tenant,
            TenantBillingAssignmentRow.status == "active",
        )))
    assert len(active) == 1 and active[0].effective_from == effective


def test_provider_pending_reconciliation_cannot_downgrade_paid_invoice():
    """Row lock orders a delayed provider result before a manual paid action."""
    class PendingProvider(_DelayedPaymentProvider):
        def __init__(self):
            super().__init__()
            self.started = threading.Event()
            self.release = threading.Event()
            self.lookups = 0

        def get_payment(self, reference):
            self.lookups += 1
            self.started.set()
            assert self.release.wait(timeout=8)
            return PaymentStatus(
                provider=self.name, status="pending", reference=reference, paid=False,
                currency="RUB", amount_minor=333,
            )

    provider = PendingProvider()
    service = _service(payment_providers={provider.name: provider})
    tenant, _, now = _setup(service, payment_provider=provider.name)
    invoice = service.finalize_invoice(
        tenant_id=tenant, period_start=now - timedelta(hours=2),
        period_end=now + timedelta(hours=2),
    )
    service.create_invoice_payment(invoice["invoice_id"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        reconciliation = pool.submit(service.sync_invoice_payment, invoice["invoice_id"])
        assert provider.started.wait(timeout=8)
        paid = pool.submit(service.mark_invoice_paid, invoice["invoice_id"])
        # Provider status is pending; payment must become paid regardless of
        # whether a later status update is attempted.
        provider.release.set()
        reconciliation.result(timeout=8)
        marked = paid.result(timeout=8)
    assert marked["status"] == "paid" and marked["paid_at"] is not None
    assert service.sync_invoice_payment(invoice["invoice_id"])["status"] == "paid"
    assert provider.lookups == 1
