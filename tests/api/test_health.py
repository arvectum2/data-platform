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
