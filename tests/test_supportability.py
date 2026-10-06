import pytest
from arvectum_data.supportability import evaluate_operation_slo, overall_readiness, percentile


def test_percentile_is_deterministic() -> None:
    assert percentile([100, 200, 300], 0.95) == 290
    assert percentile([], 0.95) == 0
    with pytest.raises(ValueError):
        percentile([1], 1.1)


def test_operation_slo_requires_minimum_window() -> None:
    result = evaluate_operation_slo(operation="search", requests=5, errors=0, latency_samples_ms=[100] * 5)
    assert result["status"] == "insufficient-data"


def test_overall_readiness_prefers_red_then_green() -> None:
    assert overall_readiness({"search": {"status": "red"}}) == "red"
    assert overall_readiness({"search": {"status": "green"}, "answer": {"status": "insufficient-data"}}) == "green"
    assert overall_readiness({"search": {"status": "insufficient-data"}}) == "insufficient-data"
