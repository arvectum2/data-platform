"""Pure public billing projections; no sessions, payments, or side effects.

Projection shape is stable for existing API and SDK consumers.
"""

from __future__ import annotations

from typing import Any

from ..billing import PriceRule
from ..storage.postgres import (
    BillingCatalogRow, TenantBillingAssignmentRow, InvoiceLineRow, UsageEventRow,
)


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


def _billing_rule_payload(rule: PriceRule) -> dict[str, Any]:
    return {
        "operation": rule.operation,
        "unit": rule.unit,
        "unit_price_minor": rule.unit_price_minor,
        "included_quantity": rule.included_quantity,
        "description": rule.description,
    }


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
