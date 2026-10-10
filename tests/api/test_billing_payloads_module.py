"""Compatibility tests for billing API projections."""

from types import SimpleNamespace

from arvectum_data.api import billing_payloads
from arvectum_data.api.service_mixins.billing import BillingServiceMixin


def test_billing_facade_uses_pure_projection_functions():
    for name in (
        "_billing_catalog_payload", "_billing_assignment_payload",
        "_billing_rule_payload", "_invoice_line_payload", "_usage_event_payload",
    ):
        assert getattr(BillingServiceMixin, name) is getattr(billing_payloads, name)


def test_billing_catalog_payload_copies_mutable_rules():
    rules = [{"operation": "ocr", "price": 1}]
    row = SimpleNamespace(
        catalog_id="c", plan_code="base", version=1, name="Базовый",
        currency="RUB", base_fee_minor=0, rules_json=rules, status="active",
        effective_from=None, created_at=None,
    )
    result = billing_payloads._billing_catalog_payload(row)
    assert result["rules"] == rules
    assert result["rules"] is not rules
    assert result["currency"] == "RUB"
