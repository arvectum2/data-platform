from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config

from arvectum_data.api.config import Settings
from arvectum_data.billing import PaymentHandoff, PaymentStatus
from arvectum_data.api.service import (
    DataPlatformService,
    InvoicePricingIncomplete,
    BillingAssignmentNotFound,
)
from arvectum_data.indexing import HashingEmbeddingProvider


pytestmark = pytest.mark.postgres


def _database_url() -> str:
    value = os.getenv("ARVECTUM_DATA_TEST_DATABASE_URL", "").strip()
    if not value:
        pytest.skip("ARVECTUM_DATA_TEST_DATABASE_URL is not configured")
    return value


def _service(*, payment_providers=None) -> DataPlatformService:
    database_url = _database_url()
    os.environ["ARVECTUM_DATA_DATABASE_URL"] = database_url
    command.upgrade(Config("alembic.ini"), "head")
    settings = Settings(
        environment="test",
        log_level="WARNING",
        database_url=database_url,
        embedding_provider="hashing",
        embedding_model="billing-test-hash",
        embedding_dimension=16,
    )
    return DataPlatformService(
        settings,
        embedding_provider=HashingEmbeddingProvider(dimension=16),
        payment_providers=payment_providers,
    )


def test_billing_catalog_usage_invoice_and_manual_payment() -> None:
    service = _service()
    suffix = uuid.uuid4().hex[:10]
    tenant_id = f"tenant-billing-{suffix}"
    consumer_id = f"consumer-billing-{suffix}"
    now = datetime.now(UTC)
    period_start = now - timedelta(hours=1)
    period_end = now + timedelta(hours=1)

    service.create_consumer_key(
        consumer_id=consumer_id,
        tenant_id=tenant_id,
        label="billing acceptance",
    )
    catalog = service.create_billing_catalog(
        plan_code=f"starter-{suffix}",
        version=1,
        name="Starter",
        currency="RUB",
        base_fee_minor=10_000,
        rules=(
            {
                "operation": "search",
                "unit": "request",
                "unit_price_minor": 250,
                "included_quantity": 1,
            },
            {
                "operation": "research",
                "unit": "request",
                "unit_price_minor": 1_000,
                "included_quantity": 0,
            },
        ),
        effective_from=now - timedelta(days=1),
    )
    service.assign_tenant_billing(
        tenant_id=tenant_id,
        catalog_id=catalog["catalog_id"],
        effective_from=now - timedelta(hours=2),
        payment_provider="manual",
    )

    service.record_usage_event(
        consumer_id=consumer_id,
        operation="search",
        request_id=f"{suffix}-search-1",
        status_code=200,
    )
    service.record_usage_event(
        consumer_id=consumer_id,
        operation="search",
        request_id=f"{suffix}-search-2",
        status_code=200,
    )
    service.record_usage_event(
        consumer_id=consumer_id,
        operation="research",
        request_id=f"{suffix}-research-1",
        status_code=200,
    )
    service.record_usage_event(
        consumer_id=consumer_id,
        operation="answer",
        request_id=f"{suffix}-failed-answer",
        status_code=500,
    )

    preview = service.preview_invoice(
        tenant_id=tenant_id,
        period_start=period_start,
        period_end=period_end,
    )
    assert preview["status"] == "preview"
    assert preview["unpriced_usage"] == []
    assert preview["base_fee_minor"] == 10_000
    assert preview["subtotal_minor"] == 11_250
    assert preview["total_minor"] == 11_250
    assert [(line["operation"], line["amount_minor"]) for line in preview["lines"]] == [
        ("research", 1_000),
        ("search", 250),
    ]

    finalized = service.finalize_invoice(
        tenant_id=tenant_id,
        period_start=period_start,
        period_end=period_end,
    )
    assert finalized["status"] == "finalized"
    assert finalized["invoice_id"]
    assert finalized["pricing_snapshot"]["plan_code"] == f"starter-{suffix}"
    assert finalized["usage_snapshot_hash"] == preview["usage_snapshot_hash"]

    retry = service.finalize_invoice(
        tenant_id=tenant_id,
        period_start=period_start,
        period_end=period_end,
    )
    assert retry["invoice_id"] == finalized["invoice_id"]

    handoff = service.create_invoice_payment(finalized["invoice_id"])
    assert handoff["payment_provider"] == "manual"
    assert handoff["provider_reference"] == f"manual:{finalized['invoice_id']}"
    assert handoff["payment_url"] is None

    paid = service.mark_invoice_paid(
        finalized["invoice_id"],
        provider_reference="bank-statement-1",
    )
    assert paid["status"] == "paid"
    assert paid["paid_at"] is not None
    assert paid["provider_reference"] == "bank-statement-1"


def test_unpriced_billable_usage_blocks_finalization() -> None:
    service = _service()
    suffix = uuid.uuid4().hex[:10]
    tenant_id = f"tenant-unpriced-{suffix}"
    consumer_id = f"consumer-unpriced-{suffix}"
    now = datetime.now(UTC)

    service.create_consumer_key(
        consumer_id=consumer_id,
        tenant_id=tenant_id,
        label="unpriced billing acceptance",
    )
    catalog = service.create_billing_catalog(
        plan_code=f"limited-{suffix}",
        version=1,
        name="Limited",
        currency="RUB",
        base_fee_minor=0,
        rules=(
            {
                "operation": "search",
                "unit": "request",
                "unit_price_minor": 100,
            },
        ),
        effective_from=now - timedelta(days=1),
    )
    service.assign_tenant_billing(
        tenant_id=tenant_id,
        catalog_id=catalog["catalog_id"],
        effective_from=now - timedelta(hours=2),
    )
    service.record_usage_event(
        consumer_id=consumer_id,
        operation="research",
        request_id=f"{suffix}-research",
        status_code=200,
    )

    preview = service.preview_invoice(
        tenant_id=tenant_id,
        period_start=now - timedelta(hours=1),
        period_end=now + timedelta(hours=1),
    )
    assert preview["unpriced_usage"] == [
        {"operation": "research", "unit": "request", "quantity": 1}
    ]
    with pytest.raises(InvoicePricingIncomplete):
        service.finalize_invoice(
            tenant_id=tenant_id,
            period_start=now - timedelta(hours=1),
            period_end=now + timedelta(hours=1),
        )


def test_assignment_change_inside_period_blocks_invoice() -> None:
    service = _service()
    suffix = uuid.uuid4().hex[:10]
    tenant_id = f"tenant-switch-{suffix}"
    now = datetime.now(UTC)

    first = service.create_billing_catalog(
        plan_code=f"switch-{suffix}",
        version=1,
        name="Switch v1",
        currency="RUB",
        base_fee_minor=0,
        rules=(
            {"operation": "search", "unit": "request", "unit_price_minor": 1},
        ),
        effective_from=now - timedelta(days=2),
    )
    second = service.create_billing_catalog(
        plan_code=f"switch-{suffix}",
        version=2,
        name="Switch v2",
        currency="RUB",
        base_fee_minor=0,
        rules=(
            {"operation": "search", "unit": "request", "unit_price_minor": 2},
        ),
        effective_from=now,
    )
    service.assign_tenant_billing(
        tenant_id=tenant_id,
        catalog_id=first["catalog_id"],
        effective_from=now - timedelta(days=1),
    )
    service.assign_tenant_billing(
        tenant_id=tenant_id,
        catalog_id=second["catalog_id"],
        effective_from=now,
    )

    with pytest.raises(BillingAssignmentNotFound):
        service.preview_invoice(
            tenant_id=tenant_id,
            period_start=now - timedelta(hours=1),
            period_end=now + timedelta(hours=1),
        )



class FakeOnlinePaymentProvider:
    name = "fake-online"

    def create_payment(self, request):
        return PaymentHandoff(
            provider=self.name,
            status="pending",
            reference=f"provider-{request.invoice_id}",
            payment_url="https://pay.example/checkout",
        )

    def get_payment(self, reference):
        return PaymentStatus(
            provider=self.name,
            status="succeeded",
            reference=reference,
            paid=True,
            amount_minor=self.expected_amount_minor,
            currency="RUB",
        )


def test_payment_provider_reconciliation_marks_invoice_paid_only_after_verification() -> None:
    provider = FakeOnlinePaymentProvider()
    service = _service(payment_providers={provider.name: provider})
    suffix = uuid.uuid4().hex[:10]
    tenant_id = f"tenant-provider-{suffix}"
    consumer_id = f"consumer-provider-{suffix}"
    now = datetime.now(UTC)

    service.create_consumer_key(
        consumer_id=consumer_id,
        tenant_id=tenant_id,
        label="provider reconciliation",
    )
    catalog = service.create_billing_catalog(
        plan_code=f"provider-{suffix}",
        version=1,
        name="Provider",
        currency="RUB",
        base_fee_minor=500,
        rules=(
            {"operation": "search", "unit": "request", "unit_price_minor": 100},
        ),
        effective_from=now - timedelta(days=1),
    )
    service.assign_tenant_billing(
        tenant_id=tenant_id,
        catalog_id=catalog["catalog_id"],
        effective_from=now - timedelta(hours=2),
        payment_provider=provider.name,
    )
    service.record_usage_event(
        consumer_id=consumer_id,
        operation="search",
        request_id=f"{suffix}-search",
        status_code=200,
    )
    invoice = service.finalize_invoice(
        tenant_id=tenant_id,
        period_start=now - timedelta(hours=1),
        period_end=now + timedelta(hours=1),
    )
    provider.expected_amount_minor = invoice["total_minor"]

    handoff = service.create_invoice_payment(invoice["invoice_id"])
    assert handoff["status"] == "finalized"
    assert handoff["provider_status"] == "pending"
    assert handoff["payment_url"] == "https://pay.example/checkout"

    synchronized = service.sync_invoice_payment(invoice["invoice_id"])
    assert synchronized["status"] == "paid"
    assert synchronized["provider_status"] == "succeeded"
    assert synchronized["paid_at"] is not None


def test_invoice_listing_batches_lines_and_snapshot_hash_is_byte_identical():
    """Invoice list is two SQL round-trips rather than one per invoice."""
    import hashlib

    from sqlalchemy import event, select
    from arvectum_data.storage.postgres import UsageEventRow

    service = _service()
    suffix = uuid.uuid4().hex[:10]
    tenant_id = f"tenant-sql-batch-{suffix}"
    consumer_id = f"consumer-sql-batch-{suffix}"
    now = datetime.now(UTC)
    service.create_consumer_key(
        consumer_id=consumer_id, tenant_id=tenant_id, label="list invoice regression"
    )
    catalog = service.create_billing_catalog(
        plan_code=f"list-{suffix}", version=1, name="List", currency="RUB",
        base_fee_minor=1234,
        rules=({"operation": "search", "unit": "request", "unit_price_minor": 17},),
        effective_from=now - timedelta(days=3),
    )
    service.assign_tenant_billing(
        tenant_id=tenant_id, catalog_id=catalog["catalog_id"],
        effective_from=now - timedelta(days=2),
    )
    for index in range(3):
        service.record_usage_event(
            consumer_id=consumer_id, operation="search", status_code=200,
            request_id=f"{suffix}-usage-{index}",
        )

    with service.session_factory() as session:
        events = list(session.scalars(
            select(UsageEventRow)
            .where(UsageEventRow.tenant_id == tenant_id)
            .order_by(UsageEventRow.usage_event_id)
        ))
    legacy_payload = "\n".join(
        f"{row.usage_event_id}:{row.operation}:{row.unit}:{row.quantity}" for row in events
    )
    expected_hash = hashlib.sha256(legacy_payload.encode()).hexdigest()

    for index in range(6):
        period_start = now - timedelta(hours=index + 1)
        period_end = now + timedelta(hours=index + 1)
        preview = service.preview_invoice(
            tenant_id=tenant_id, period_start=period_start, period_end=period_end,
        )
        assert preview["usage_snapshot_hash"] == expected_hash
        finalized = service.finalize_invoice(
            tenant_id=tenant_id, period_start=period_start, period_end=period_end,
        )
        assert finalized["total_minor"] == 1234 + 3 * 17
        assert finalized["usage_snapshot_hash"] == expected_hash

    engine = service.session_factory.kw["bind"]
    executed = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        executed.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        invoices = service.list_invoices(tenant_id=tenant_id)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(invoices) == 6
    assert len(executed) == 2, f"invoice list issued {len(executed)} SQL calls"
    assert all(len(invoice["lines"]) == 1 for invoice in invoices)
    assert all(invoice["total_minor"] == 1285 for invoice in invoices)
    assert all(invoice["usage_snapshot_hash"] == expected_hash for invoice in invoices)
    assert [invoice["period_end"] for invoice in invoices] == sorted(
        (invoice["period_end"] for invoice in invoices), reverse=True
    )


def test_usage_event_concurrent_replays_are_idempotent():
    """Two workers must not create duplicates or overwrite the first event."""
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import func, select
    from arvectum_data.storage.postgres import UsageEventRow

    service = _service()
    suffix = uuid.uuid4().hex[:12]
    consumer_id = f"consumer-concurrent-{suffix}"
    tenant_id = f"tenant-concurrent-{suffix}"
    request_id = f"request-concurrent-{suffix}"
    service.create_consumer_key(
        consumer_id=consumer_id, tenant_id=tenant_id, label="concurrent usage"
    )

    def record(_):
        return service.record_usage_event(
            consumer_id=consumer_id, request_id=request_id,
            operation="search", status_code=200, quantity=1,
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(record, range(12)))
    assert len({item["usage_event_id"] for item in results}) == 1
    assert all(item["quantity"] == 1 for item in results)
    assert all(item["tenant_id"] == tenant_id for item in results)
    with service.session_factory() as session:
        count = session.scalar(select(func.count()).select_from(UsageEventRow).where(
            UsageEventRow.consumer_id == consumer_id,
            UsageEventRow.request_id == request_id,
        ))
    assert count == 1

    replay = service.record_usage_event(
        consumer_id=consumer_id, request_id=request_id,
        operation="search", status_code=503, quantity=100,
    )
    assert replay == results[0]
