from __future__ import annotations

from fastapi.testclient import TestClient

from arvectum_data.api.app import create_app
from arvectum_data.api.config import Settings
from tests.api.test_v1_contract import FakePlatformService


class UsagePlatformService(FakePlatformService):
    def __init__(self, *, fail_metering: bool = False) -> None:
        self.usage_events: list[dict] = []
        self.fail_metering = fail_metering

    def record_usage_event(self, **kwargs):
        if self.fail_metering:
            raise RuntimeError("metering unavailable")
        self.usage_events.append(dict(kwargs))
        return dict(kwargs)

    def usage_summary(self, **kwargs):
        return {
            "since": kwargs.get("since"),
            "until": kwargs.get("until"),
            "total_events": len(self.usage_events),
            "total_quantity": len(self.usage_events),
            "billable_quantity": sum(
                1
                for item in self.usage_events
                if 200 <= int(item["status_code"]) < 400
            ),
            "buckets": [],
        }


def _client(platform: UsagePlatformService) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                environment="test",
                log_level="WARNING",
                internal_api_key="admin-secret",
                consumer_api_keys={"external": "consumer-secret"},
            ),
            platform_service=platform,
        )
    )


def _search(client: TestClient, *, secret: str = "consumer-secret"):
    return client.post(
        "/v1/search",
        headers={
            "X-Arvectum-Consumer": "external",
            "X-Arvectum-Consumer-Key": secret,
            "X-Request-ID": "req-usage-1",
        },
        json={
            "query": "private query must never be persisted in usage metadata",
            "collections": ["tests:knowledge"],
            "limit": 1,
            "mode": "lexical",
        },
    )


def test_authenticated_search_records_content_free_usage_event() -> None:
    platform = UsagePlatformService()
    client = _client(platform)

    response = _search(client)

    assert response.status_code == 200
    assert len(platform.usage_events) == 1
    event = platform.usage_events[0]
    assert event["consumer_id"] == "external"
    assert event["operation"] == "search"
    assert event["request_id"] == "req-usage-1"
    assert event["status_code"] == 200
    assert event["duration_ms"] >= 0
    assert event["request_bytes"] > 0
    assert "query" not in event
    assert "private query" not in repr(event)

    summary = client.get(
        "/v1/usage/summary?consumer_id=external",
        headers={"X-Arvectum-Key": "admin-secret"},
    )
    assert summary.status_code == 200
    assert summary.json()["total_events"] == 1
    assert summary.json()["billable_quantity"] == 1


def test_invalid_consumer_credentials_are_not_metered() -> None:
    platform = UsagePlatformService()
    client = _client(platform)

    response = _search(client, secret="wrong")

    assert response.status_code == 403
    assert platform.usage_events == []


def test_metering_failure_does_not_take_search_down() -> None:
    platform = UsagePlatformService(fail_metering=True)
    client = _client(platform)

    response = _search(client)

    assert response.status_code == 200
    status = client.get(
        "/v1/status",
        headers={"X-Arvectum-Key": "admin-secret"},
    )
    assert status.status_code == 200
    assert status.json()["metrics"]["usage_metering_errors"] == 1
