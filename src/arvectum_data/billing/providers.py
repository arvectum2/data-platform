from __future__ import annotations

import base64
import json
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Protocol, runtime_checkable
from urllib.parse import quote, urlsplit


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


@dataclass(frozen=True, slots=True)
class PaymentStatus:
    provider: str
    status: str
    reference: str
    paid: bool
    amount_minor: int | None = None
    currency: str | None = None


@runtime_checkable
class PaymentProvider(Protocol):
    name: str

    def create_payment(self, request: PaymentRequest) -> PaymentHandoff: ...

    def get_payment(self, reference: str) -> PaymentStatus: ...


class ManualPaymentProvider:
    name = "manual"

    def create_payment(self, request: PaymentRequest) -> PaymentHandoff:
        return PaymentHandoff(
            provider=self.name,
            status="pending",
            reference=f"manual:{request.invoice_id}",
            payment_url=None,
        )

    def get_payment(self, reference: str) -> PaymentStatus:
        return PaymentStatus(
            provider=self.name,
            status="pending",
            reference=reference,
            paid=False,
        )


class YooKassaPaymentProvider:
    name = "yookassa"
    DEFAULT_BASE_URL = "https://api.yookassa.ru/v3"

    def __init__(
        self,
        *,
        shop_id: str,
        secret_key: str,
        return_url: str,
        payment_method: str = "smart",
        timeout_seconds: float = 10.0,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self.shop_id = shop_id.strip()
        self.secret_key = secret_key.strip()
        self.return_url = return_url.strip()
        self.payment_method = payment_method.strip().lower()
        self.timeout_seconds = float(timeout_seconds)
        self.base_url = base_url.rstrip("/")

        if not self.shop_id:
            raise ValueError("YooKassa shop_id must not be blank")
        if not self.secret_key:
            raise ValueError("YooKassa secret_key must not be blank")
        parsed_return = urlsplit(self.return_url)
        if parsed_return.scheme != "https" or not parsed_return.netloc:
            raise ValueError("YooKassa return_url must be an absolute HTTPS URL")
        if self.payment_method not in {"smart", "sbp"}:
            raise ValueError("YooKassa payment_method must be smart or sbp")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 60:
            raise ValueError("YooKassa timeout_seconds must be in (0, 60]")
        parsed_api = urlsplit(self.base_url)
        if parsed_api.scheme != "https" or not parsed_api.netloc:
            raise ValueError("YooKassa API base_url must be HTTPS")

    def _authorization(self) -> str:
        raw = f"{self.shop_id}:{self.secret_key}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        idempotence_key: str | None = None,
    ) -> dict[str, object]:
        headers = {
            "Accept": "application/json",
            "Authorization": self._authorization(),
            "User-Agent": "Arvectum-Data-Platform/0.6",
        }
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        if idempotence_key is not None:
            headers["Idempotence-Key"] = idempotence_key

        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            decoded = json.loads(response.read().decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("YooKassa returned a non-object response")
        return decoded

    @staticmethod
    def _amount_value(amount_minor: int, currency: str) -> str:
        if amount_minor < 0:
            raise ValueError("payment amount must be non-negative")
        if currency.upper() != "RUB":
            raise ValueError("YooKassa adapter currently supports RUB invoices only")
        value = (Decimal(amount_minor) / Decimal(100)).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        return format(value, "f")

    @staticmethod
    def _minor_amount(value: object, currency: object) -> int | None:
        if value is None or str(currency or "").upper() != "RUB":
            return None
        try:
            decimal = Decimal(str(value)).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        except InvalidOperation:
            return None
        return int(decimal * 100)

    def create_payment(self, request: PaymentRequest) -> PaymentHandoff:
        payload: dict[str, object] = {
            "amount": {
                "value": self._amount_value(
                    request.amount_minor,
                    request.currency,
                ),
                "currency": request.currency.upper(),
            },
            "capture": True,
            "confirmation": {
                "type": "redirect",
                "return_url": self.return_url,
            },
            "description": request.description[:128],
            "metadata": {
                "invoice_id": request.invoice_id,
                "tenant_id": request.tenant_id,
            },
        }
        if self.payment_method == "sbp":
            payload["payment_method_data"] = {"type": "sbp"}

        response = self._request(
            "POST",
            "/payments",
            payload=payload,
            idempotence_key=f"arvectum-invoice-{request.invoice_id}",
        )
        reference = str(response.get("id") or "").strip()
        status = str(response.get("status") or "").strip()
        if not reference or not status:
            raise ValueError("YooKassa payment response is missing id/status")
        confirmation = response.get("confirmation")
        payment_url = None
        if isinstance(confirmation, dict):
            raw_url = confirmation.get("confirmation_url")
            if raw_url is not None:
                payment_url = str(raw_url)

        return PaymentHandoff(
            provider=self.name,
            status=status,
            reference=reference,
            payment_url=payment_url,
        )

    def get_payment(self, reference: str) -> PaymentStatus:
        reference = reference.strip()
        if not reference:
            raise ValueError("YooKassa payment reference must not be blank")
        response = self._request(
            "GET",
            f"/payments/{quote(reference, safe='')}",
        )
        status = str(response.get("status") or "").strip()
        response_id = str(response.get("id") or "").strip()
        if not status or not response_id:
            raise ValueError("YooKassa payment status response is missing id/status")
        amount = response.get("amount")
        amount_minor = None
        currency = None
        if isinstance(amount, dict):
            currency = str(amount.get("currency") or "").upper() or None
            amount_minor = self._minor_amount(amount.get("value"), currency)
        return PaymentStatus(
            provider=self.name,
            status=status,
            reference=response_id,
            paid=bool(response.get("paid")) and status == "succeeded",
            amount_minor=amount_minor,
            currency=currency,
        )
