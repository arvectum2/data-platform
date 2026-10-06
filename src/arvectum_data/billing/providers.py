from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class PaymentRequest:
    invoice_id: str
    tenant_id: str
    currency: str
    amount_minor: int
    description: str


@dataclass(frozen=True, slots=True)
class PaymentHandoff:
    provider: str
    status: str
    reference: str
    payment_url: str | None = None


@runtime_checkable
class PaymentProvider(Protocol):
    name: str

    def create_payment(self, request: PaymentRequest) -> PaymentHandoff: ...


class ManualPaymentProvider:
    name = "manual"

    def create_payment(self, request: PaymentRequest) -> PaymentHandoff:
        return PaymentHandoff(
            provider=self.name,
            status="pending",
            reference=f"manual:{request.invoice_id}",
            payment_url=None,
        )
