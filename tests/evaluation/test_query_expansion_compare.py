from __future__ import annotations

from arvectum_data.evaluation import (
    EvaluationCase,
    EvaluationSuite,
    compare_query_expansion,
)


def _suite() -> EvaluationSuite:
    return EvaluationSuite(
        name="query-expansion-hard",
        cases=(
            EvaluationCase(
                case_id="hard",
                query="query",
                collections=("docs",),
                expected_ids=("expected",),
            ),
        ),
    )


def test_query_expansion_comparison_reports_gain() -> None:
    baseline_hits = [
        {"canonical_uri": "wrong"},
        {"canonical_uri": "expected"},
    ]
    expanded_hits = [
        {"canonical_uri": "expected"},
        {"canonical_uri": "wrong"},
    ]

    result = compare_query_expansion(
        _suite(),
        baseline_runner=lambda case: (baseline_hits, 100.0),
        expanded_runner=lambda case: (expanded_hits, 150.0),
    )

    assert result.passed is True
    assert result.error_type is None
    assert result.gate["mrr_gain"] == 0.5
    assert result.gate["top1_gain"] == 1.0


def test_query_expansion_comparison_fails_closed_on_timeout() -> None:
    def timeout_runner(case):
        raise TimeoutError("synthetic expansion timeout")

    result = compare_query_expansion(
        _suite(),
        baseline_runner=lambda case: (
            [{"canonical_uri": "expected"}],
            100.0,
        ),
        expanded_runner=timeout_runner,
    )

    assert result.passed is False
    assert result.expanded is None
    assert result.error_type == "TimeoutError"
    assert result.gate["reason"] == "query_expansion_execution_failed"
