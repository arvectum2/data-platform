from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from arvectum_data.api.app import create_app
from arvectum_data.api.config import Settings
from arvectum_data.api.service import DataPlatformService
from arvectum_data.billing import YooKassaPaymentProvider
from arvectum_data.indexing import HashingEmbeddingProvider


def _service(settings: Settings) -> DataPlatformService:
    return DataPlatformService(
        settings,
        embedding_provider=HashingEmbeddingProvider(dimension=16),
    )


def test_yookassa_is_disabled_by_default() -> None:
    settings = Settings(
        environment="test",
        log_level="WARNING",
        embedding_provider="hashing",
        embedding_dimension=16,
    )
    service = _service(settings)

    assert settings.yookassa_enabled is False
    assert sorted(service.payment_providers) == ["manual"]


def test_complete_yookassa_runtime_config_registers_provider_without_secret_leak() -> None:
    secret = "merchant-secret-value"
    settings = Settings(
        environment="test",
        log_level="WARNING",
        embedding_provider="hashing",
        embedding_dimension=16,
        yookassa_shop_id="shop-123",
        yookassa_secret_key=secret,
        yookassa_return_url="https://arvectum.example/billing/return",
        yookassa_payment_method="sbp",
        yookassa_timeout_seconds=7.5,
    )
    service = _service(settings)

    assert settings.yookassa_enabled is True
    assert sorted(service.payment_providers) == ["manual", "yookassa"]
    provider = service.payment_providers["yookassa"]
    assert isinstance(provider, YooKassaPaymentProvider)
    assert provider.shop_id == "shop-123"
    assert provider.payment_method == "sbp"
    assert provider.timeout_seconds == 7.5
    assert secret not in repr(settings)
    assert secret not in repr(settings.model_dump())

    app = create_app(settings, platform_service=service)
    response = TestClient(app).get("/v1/status")
    assert response.status_code == 200
    body = response.json()
    assert body["payment_providers"] == ["manual", "yookassa"]
    assert secret not in response.text
    assert "shop-123" not in response.text


@pytest.mark.parametrize(
    "kwargs",
    [
        {"yookassa_shop_id": "shop-only"},
        {"yookassa_secret_key": "secret-only"},
        {"yookassa_return_url": "https://example.com/return"},
        {
            "yookassa_shop_id": "shop",
            "yookassa_secret_key": "secret",
        },
    ],
)
def test_partial_yookassa_runtime_config_fails_closed(kwargs: dict[str, str]) -> None:
    with pytest.raises(ValidationError, match="must include shop_id, secret_key and return_url"):
        Settings(**kwargs)


def test_invalid_yookassa_payment_method_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must be smart or sbp"):
        Settings(yookassa_payment_method="crypto")


def test_local_private_rejects_yookassa_activation() -> None:
    with pytest.raises(
        ValidationError,
        match="YooKassa is not permitted in local-private mode",
    ):
        Settings(
            deployment_mode="local-private",
            yookassa_shop_id="shop",
            yookassa_secret_key="secret",
            yookassa_return_url="https://example.com/return",
        )
