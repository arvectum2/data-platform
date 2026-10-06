from __future__ import annotations

import base64
import json

import pytest

from arvectum_data.billing import PaymentRequest, YooKassaPaymentProvider


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_yookassa_sbp_create_payment_uses_idempotence_and_redirect(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse(
            {
                "id": "payment-1",
                "status": "pending",
                "confirmation": {
                    "type": "redirect",
                    "confirmation_url": "https://pay.example/confirm",
                },
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = YooKassaPaymentProvider(
        shop_id="shop-test",
        secret_key="credential-test",
        return_url="https://app.example/billing/return",
        payment_method="sbp",
        timeout_seconds=7,
        base_url="https://payments.example/v3",
    )

    handoff = provider.create_payment(
        PaymentRequest(
            invoice_id="invoice-123",
            tenant_id="tenant-1",
            currency="RUB",
            amount_minor=12_345,
            description="Invoice 123",
        )
    )

    assert handoff.provider == "yookassa"
    assert handoff.reference == "payment-1"
    assert handoff.status == "pending"
    assert handoff.payment_url == "https://pay.example/confirm"
    assert captured["url"] == "https://payments.example/v3/payments"
    assert captured["timeout"] == 7
    assert captured["headers"]["Idempotence-key"] == "arvectum-invoice-invoice-123"
    auth = captured["headers"]["Authorization"]
    assert base64.b64decode(auth.split(" ", 1)[1]).decode() == (
        "shop-test:credential-test"
    )
    assert captured["payload"]["amount"] == {
        "value": "123.45",
        "currency": "RUB",
    }
    assert captured["payload"]["capture"] is True
    assert captured["payload"]["payment_method_data"] == {"type": "sbp"}
    assert captured["payload"]["confirmation"] == {
        "type": "redirect",
        "return_url": "https://app.example/billing/return",
    }
    assert captured["payload"]["metadata"] == {
        "invoice_id": "invoice-123",
        "tenant_id": "tenant-1",
    }


def test_yookassa_smart_payment_omits_explicit_payment_method(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"id": "payment-2", "status": "pending"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = YooKassaPaymentProvider(
        shop_id="shop-test",
        secret_key="credential-test",
        return_url="https://app.example/return",
        payment_method="smart",
        base_url="https://payments.example/v3",
    )

    provider.create_payment(
        PaymentRequest(
            invoice_id="invoice-2",
            tenant_id="tenant-2",
            currency="RUB",
            amount_minor=100,
            description="invoice",
        )
    )

    assert "payment_method_data" not in captured["payload"]


def test_yookassa_get_payment_returns_verified_money_fields(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        assert request.full_url == "https://payments.example/v3/payments/payment-3"
        return FakeResponse(
            {
                "id": "payment-3",
                "status": "succeeded",
                "paid": True,
                "amount": {"value": "42.50", "currency": "RUB"},
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = YooKassaPaymentProvider(
        shop_id="shop-test",
        secret_key="credential-test",
        return_url="https://app.example/return",
        base_url="https://payments.example/v3",
    )

    status = provider.get_payment("payment-3")

    assert status.status == "succeeded"
    assert status.paid is True
    assert status.amount_minor == 4250
    assert status.currency == "RUB"


def test_yookassa_adapter_rejects_non_rub_invoice() -> None:
    provider = YooKassaPaymentProvider(
        shop_id="shop-test",
        secret_key="credential-test",
        return_url="https://app.example/return",
        base_url="https://payments.example/v3",
    )

    with pytest.raises(ValueError, match="RUB"):
        provider.create_payment(
            PaymentRequest(
                invoice_id="invoice-4",
                tenant_id="tenant-4",
                currency="USD",
                amount_minor=100,
                description="invoice",
            )
        )
