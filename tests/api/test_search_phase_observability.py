"""Source-safe numerical search phase observation; no live model or DB."""
from __future__ import annotations

import json
from collections import deque

import pytest
from fastapi.testclient import TestClient

from arvectum_data.api.app import create_app
from arvectum_data.api.config import Settings
from arvectum_data.api.search_observability import (
    numeric_search_sample,
    search_phase_readiness,
)
from arvectum_data.search.models import SearchStageDiagnostic


def stage(name: str, duration: float, *, status: str = "executed"):
    return SearchStageDiagnostic(
        stage=name, status=status, duration_ms=duration,
        provider="PRIVATE_PROVIDER",
        model="PRIVATE_MODEL",
        metadata={"query": "SECRET_QUERY", "source": "SECRET_SOURCE"},
    )


def test_numeric_only_sample_ignores_every_source_and_provider_field():
    sample = numeric_search_sample(
        [stage("embedding-query", 1200.1), stage("vector-retrieval", 19.1),
         stage("total-search", 1300.2), stage("unknown PRIVATE_NAME", 500.0),
         stage("rerank", 700, status="skipped-unavailable")]
    )
    assert sample == {
        "stages_ms": {
            "embedding-query": 1201,
            "vector-retrieval": 20,
            "total-search": 1301,
        },
    }
    assert "SECRET" not in json.dumps(sample)


@pytest.mark.parametrize("duration", [float("nan"), float("inf"), -2, "10", True, None, 4_000_000])
def test_invalid_duration_never_enters_phase_samples(duration):
    sample = numeric_search_sample([
        stage("total-search", 500),
        stage("embedding-query", duration),
    ])
    assert sample == {"stages_ms": {"total-search": 500}}


def test_incomplete_search_diagnostics_does_not_create_sample():
    assert numeric_search_sample([stage("embedding-query", 500)]) is None
    assert numeric_search_sample([stage("total-search", 1, status="skipped-unavailable")]) is None


def test_stage_p95_has_independent_sample_coverage():
    samples = deque(maxlen=256)
    for _ in range(20):
        samples.append(numeric_search_sample([
            stage("embedding-query", 1000),
            stage("vector-retrieval", 100),
            stage("total-search", 1500),
            stage("rerank", 9, status="skipped-unavailable"),
        ]))
    result = search_phase_readiness(samples)
    assert result["samples"] == 20
    assert result["sufficient_samples"] is True
    assert result["stage_samples"]["embedding-query"] == 20
    assert result["stage_sufficient_samples"]["embedding-query"] is True
    assert result["stage_p95_ms"]["embedding-query"] == 1000
    assert result["stage_p95_ms"]["rerank"] is None
    assert result["stage_samples"]["rerank"] == 0
    assert result["content_included"] is False


def test_bounded_window_excludes_earlier_slow_samples():
    historical = [
        {"stages_ms": {"total-search": 70000, "embedding-query": 60000}}
        for _ in range(44)
    ] + [
        {"stages_ms": {"total-search": 100, "embedding-query": 70}}
        for _ in range(256)
    ]
    report = search_phase_readiness(historical)
    assert report["samples"] == 256
    assert report["stage_p95_ms"]["total-search"] == 100
    assert report["stage_p95_ms"]["embedding-query"] == 70


def test_malicious_telemetry_injection_cannot_leak_or_count_invalid():
    samples = [
        {"stages_ms": {"total-search": 40, "SECRET_KEY": 999},
         "source": "PRIVATE_SOURCE", "query": "PRIVATE_QUERY"},
        {"stages_ms": {"total-search": float("nan"), "embedding-query": 100}},
        {"stages_ms": {"total-search": True}},
        {"stages_ms": {"total-search": 20, "rerank": "SECRET_TEXT"}},
    ]
    result = search_phase_readiness(samples)
    assert result["samples"] == 2
    assert result["stage_samples"]["rerank"] == 0
    assert "SECRET" not in json.dumps(result)
    assert "PRIVATE" not in json.dumps(result)


def test_readiness_get_includes_only_numeric_existing_search_phases():
    app = create_app(Settings(environment="test", log_level="WARNING"))
    app.state.search_phase_samples.append(numeric_search_sample([
        stage("embedding-query", 42),
        stage("total-search", 49),
    ]))
    client = TestClient(app)
    response = client.get("/v1/support/readiness")
    assert response.status_code == 200
    payload = response.json()
    assert payload["search_phases"]["samples"] == 1
    assert payload["search_phases"]["stage_p95_ms"]["embedding-query"] == 42
    assert payload["operations"]["search"]["status"] == "insufficient-data"
    assert "PRIVATE_MODEL" not in response.text
    assert "SECRET_QUERY" not in response.text


def test_real_route_with_synthetic_service_observes_only_successful_numeric_stages():
    class SyntheticSearch:
        def search_with_execution_diagnostics(self, request, *, consumer=None):
            return [], (), (
                stage("embedding-query", 250.4),
                stage("vector-retrieval", 12.1),
                stage("total-search", 270.2),
            )

    app = create_app(
        Settings(environment="test", log_level="WARNING"),
        platform_service=SyntheticSearch(),
    )
    client = TestClient(app)
    response = client.post(
        "/v1/search",
        json={"query": "UNTRUSTED QUERY NEVER TO LEAK", "collections": ["synthetic"]},
    )
    assert response.status_code == 200, response.text
    support = client.get("/v1/support/readiness")
    assert support.status_code == 200
    body = support.json()
    assert body["search_phases"]["samples"] == 1
    assert body["search_phases"]["stage_p95_ms"]["embedding-query"] == 251
    assert body["search_phases"]["stage_p95_ms"]["total-search"] == 271
    assert "UNTRUSTED QUERY" not in support.text
    assert "SECRET_SOURCE" not in support.text
