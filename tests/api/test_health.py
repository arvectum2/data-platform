from fastapi.testclient import TestClient

from arvectum_data.api.app import create_app
from arvectum_data.api.config import Settings


def test_health() -> None:
    client = TestClient(
        create_app(
            Settings(
                service_name="arvectum-data-test",
                environment="test",
                log_level="WARNING",
            )
        )
    )

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "arvectum-data-test"
    assert payload["environment"] == "test"
    assert payload["version"]


def test_model_status_is_disabled_by_default() -> None:
    client = TestClient(create_app(Settings(environment="test", log_level="WARNING")))

    response = client.get("/v1/models/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["reasoning"]["enabled"] is False
    assert payload["vision"]["enabled"] is False


def test_status_exposes_configured_local_reasoning_role_without_probe() -> None:
    client = TestClient(
        create_app(
            Settings(
                environment="test",
                log_level="WARNING",
                reasoning_policy="local-only",
                reasoning_model="local-reasoner",
                reasoning_base_url="http://127.0.0.1:9000/v1",
            )
        )
    )

    response = client.get("/v1/status")

    assert response.status_code == 200
    role = response.json()["model_roles"]["reasoning"]
    assert role["enabled"] is True
    assert role["provider"] == "openai-compatible"
    assert role["model"] == "local-reasoner"
    assert role["locality"] == "local"
