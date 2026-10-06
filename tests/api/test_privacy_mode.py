from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from arvectum_data.api.app import create_app
from arvectum_data.api.config import Settings


def test_local_private_accepts_loopback_core() -> None:
    settings = Settings(
        deployment_mode="local-private",
        database_url="postgresql+psycopg://user:pass@127.0.0.1:5432/data",
        embedding_provider="llama_cpp",
        embedding_base_url="http://127.0.0.1:8090/v1",
        reasoning_policy="local-only",
        reasoning_model="local-reasoner",
        reasoning_base_url="http://127.0.0.1:8080/v1",
        reasoning_locality="local",
        vision_policy="disabled",
        ocr_provider="tesseract",
    )
    assert settings.deployment_mode == "local-private"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("host", "0.0.0.0"),
        ("database_url", "postgresql+psycopg://u:p@db.example.com/data"),
        ("embedding_base_url", "https://embeddings.example.com/v1"),
        ("cross_encoder_base_url", "https://rerank.example.com"),
    ],
)
def test_local_private_rejects_remote_core_endpoints(field: str, value: str) -> None:
    kwargs = {
        "deployment_mode": "local-private",
        "embedding_provider": "llama_cpp",
        "embedding_base_url": "http://127.0.0.1:8090/v1",
    }
    kwargs[field] = value
    with pytest.raises(ValidationError, match="local-private deployment rejects"):
        Settings(**kwargs)


def test_local_private_rejects_remote_reasoning_policy() -> None:
    with pytest.raises(ValidationError, match="reasoning policy"):
        Settings(
            deployment_mode="local-private",
            reasoning_policy="remote-allowlist",
            reasoning_locality="remote",
            reasoning_model="remote-model",
            reasoning_base_url="https://llm.example.com/v1",
            reasoning_remote_allowlist="llm.example.com",
        )


def test_local_private_rejects_stale_remote_allowlist() -> None:
    with pytest.raises(ValidationError, match="vision remote allowlist"):
        Settings(
            deployment_mode="local-private",
            vision_policy="disabled",
            vision_remote_allowlist="vision.example.com",
        )


def test_status_exposes_deployment_mode() -> None:
    client = TestClient(
        create_app(
            Settings(
                environment="test",
                log_level="WARNING",
                deployment_mode="local-private",
            )
        )
    )
    response = client.get("/v1/status")
    assert response.status_code == 200
    assert response.json()["deployment_mode"] == "local-private"


def test_cross_encoder_provider_is_validated() -> None:
    with pytest.raises(ValidationError, match="cross_encoder_provider"):
        Settings(cross_encoder_provider="unknown")
