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


def test_mode_and_feature_cohorts_separate_mixed_search_without_source_data():
    from arvectum_data.search.models import SearchMode

    samples = deque(maxlen=256)
    for _ in range(24):
        samples.append(numeric_search_sample(
            [stage("lexical-retrieval", 48), stage("total-search", 100)],
            mode=SearchMode.LEXICAL,
            rerank_requested=False,
            expansion_requested=False,
        ))
    for _ in range(24):
        samples.append(numeric_search_sample(
            [stage("embedding-query", 10000), stage("vector-retrieval", 700),
             stage("total-search", 11000)],
            mode=SearchMode.VECTOR,
            rerank_requested=False,
            expansion_requested=False,
        ))
    for _ in range(24):
        samples.append(numeric_search_sample(
            [stage("query-expansion", 2500), stage("embedding-query", 5500),
             stage("lexical-retrieval", 45), stage("vector-retrieval", 50),
             stage("rerank", 4100), stage("total-search", 14500)],
            mode=SearchMode.HYBRID,
            rerank_requested=True,
            expansion_requested=True,
        ))
    result = search_phase_readiness(samples)
    assert result["samples"] == 72
    assert result["by_mode"]["lexical"]["samples"] == 24
    assert result["by_mode"]["lexical"]["stage_p95_ms"]["total-search"] == 100
    assert result["by_mode"]["lexical"]["stage_p95_ms"]["embedding-query"] is None
    assert result["by_mode"]["vector"]["stage_p95_ms"]["embedding-query"] == 10000
    assert result["by_mode"]["hybrid"]["stage_p95_ms"]["rerank"] == 4100
    assert result["by_mode"]["hybrid"]["stage_p95_ms"]["query-expansion"] == 2500
    assert result["by_rerank_requested"]["yes"]["samples"] == 24
    assert result["by_rerank_requested"]["no"]["samples"] == 48
    assert result["by_expansion_requested"]["yes"]["samples"] == 24
    assert result["by_expansion_requested"]["no"]["samples"] == 48
    assert result["content_included"] is False
    assert "SECRET" not in json.dumps(result)
    assert "PRIVATE" not in json.dumps(result)


def test_untrusted_cohort_labels_never_leak_and_legacy_is_unknown():
    rows = [
        numeric_search_sample(
            [stage("total-search", 120)],
            mode="PRIVATE_DATA_FROM_CLIENT",
            rerank_requested="SECRET_QUERY",
            expansion_requested=5,
        ),
        numeric_search_sample([stage("total-search", 42)]),
    ]
    assert rows[0] == {"stages_ms": {"total-search": 120}, "mode": "unknown"}
    result = search_phase_readiness(rows)
    assert result["by_mode"]["unknown"]["samples"] == 2
    assert result["by_mode"]["unknown"]["sufficient_samples"] is False
    assert result["by_rerank_requested"] == {}
    assert result["by_expansion_requested"] == {}
    assert "PRIVATE" not in json.dumps(result)
    assert "SECRET" not in json.dumps(result)


def test_bounded_mode_cohort_window_is_not_historical_full_request_slo():
    old = [
        numeric_search_sample([stage("total-search", 65000)], mode="vector")
        for _ in range(300)
    ]
    newest = [
        numeric_search_sample([stage("total-search", 400)], mode="lexical")
        for _ in range(256)
    ]
    result = search_phase_readiness(old + newest)
    assert result["samples"] == 256
    assert result["by_mode"]["lexical"]["samples"] == 256
    assert "vector" not in result["by_mode"]
    assert result["stage_p95_ms"]["total-search"] == 400
    assert result["window_size"] == 256
    assert "not an HTTP SLO" in result["note"]


def test_synthetic_route_records_only_whitelisted_request_cohort():
    class SyntheticSearch:
        def search_with_execution_diagnostics(self, request, *, consumer=None):
            assert request.mode.value == "vector"
            assert request.expand_query is False
            assert request.rerank is False
            return [], (), (
                stage("embedding-query", 140),
                stage("vector-retrieval", 18),
                stage("total-search", 190),
            )

    app = create_app(
        Settings(environment="test", log_level="WARNING", internal_api_key="secret"),
        platform_service=SyntheticSearch(),
    )
    client = TestClient(app)
    response = client.post(
        "/v1/search",
        headers={"X-Arvectum-Key": "secret"},
        json={
            "query": "SECRET_QUERY_STRING_NOT_ALLOWED_IN_AGGREGATE",
            "collections": ["PRIVATE_COLLECTION_ID"],
            "mode": "vector",
            "rerank": False,
            "expand_query": False,
        },
    )
    assert response.status_code == 200, response.text
    unauthorized = client.get("/v1/support/readiness")
    assert unauthorized.status_code == 401
    support = client.get("/v1/support/readiness", headers={"X-Arvectum-Key": "secret"})
    assert support.status_code == 200
    report = support.json()["search_phases"]
    assert report["by_mode"]["vector"]["samples"] == 1
    assert report["by_mode"]["vector"]["stage_p95_ms"]["embedding-query"] == 140
    assert report["by_rerank_requested"]["no"]["samples"] == 1
    assert report["by_expansion_requested"]["no"]["samples"] == 1
    assert report["by_mode"]["vector"]["sufficient_samples"] is False
    assert "PRIVATE_COLLECTION_ID" not in support.text
    assert "SECRET_QUERY" not in support.text
    assert "PRIVATE_MODEL" not in support.text
