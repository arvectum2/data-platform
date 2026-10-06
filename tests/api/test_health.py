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


def test_support_readiness_is_insufficient_without_sample_window() -> None:
    app = create_app(Settings(environment="test", log_level="WARNING"))
    client = TestClient(app)
    response = client.get("/v1/support/readiness")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "insufficient-data"
    assert payload["window_size"] == 256
    assert payload["operations"]["search"]["status"] == "insufficient-data"


def test_support_readiness_reports_green_and_red_operations() -> None:
    app = create_app(Settings(environment="test", log_level="WARNING"))
    app.state.operation_metrics["search"].update(requests=20, errors=0, total_ms=2000, max_ms=150)
    app.state.operation_latency_samples["search"].extend([100] * 20)
    app.state.operation_metrics["answer"].update(requests=20, errors=2, total_ms=200000, max_ms=15000)
    app.state.operation_latency_samples["answer"].extend([10000] * 20)
    client = TestClient(app)
    response = client.get("/v1/support/readiness")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "red"
    assert payload["operations"]["search"]["status"] == "green"
    assert payload["operations"]["search"]["p95_ms"] == 100
    assert payload["operations"]["answer"]["status"] == "red"
    assert payload["operations"]["answer"]["error_rate"] == 0.1


def test_status_exposes_bounded_p95_window_metrics() -> None:
    app = create_app(Settings(environment="test", log_level="WARNING"))
    app.state.operation_metrics["search"].update(requests=3, errors=0, total_ms=600, max_ms=300)
    app.state.operation_latency_samples["search"].extend([100, 200, 300])
    client = TestClient(app)
    response = client.get("/v1/status")
    assert response.status_code == 200
    search = response.json()["operations"]["search"]
    assert search["window_samples"] == 3
    assert search["p95_ms"] == 290
