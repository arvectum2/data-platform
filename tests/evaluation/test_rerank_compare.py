from __future__ import annotations

from arvectum_data.evaluation import (
    EvaluationCase,
    EvaluationSuite,
    compare_reranking,
)


def _suite() -> EvaluationSuite:
    return EvaluationSuite(
        name="rerank-hard",
        cases=(
            EvaluationCase(
                case_id="hard",
                query="query",
                collections=("docs",),
                expected_ids=("expected",),
            ),
        ),
    )


def test_rerank_comparison_reports_quality_gain() -> None:
    baseline_hits = [
        {"canonical_uri": "wrong"},
        {"canonical_uri": "expected"},
    ]
    reranked_hits = [
        {"canonical_uri": "expected"},
        {"canonical_uri": "wrong"},
    ]

    result = compare_reranking(
        _suite(),
        baseline_runner=lambda case: (baseline_hits, 100.0),
        reranked_runner=lambda case: (reranked_hits, 200.0),
    )

    assert result.passed is True
    assert result.error_type is None
    assert result.gate["mrr_gain"] == 0.5
    assert result.gate["top1_gain"] == 1.0


def test_rerank_comparison_fails_closed_on_timeout() -> None:
    def timeout_runner(case):
        raise TimeoutError("synthetic rerank timeout")

    result = compare_reranking(
        _suite(),
        baseline_runner=lambda case: (
            [{"canonical_uri": "expected"}],
            100.0,
        ),
        reranked_runner=timeout_runner,
    )

    assert result.passed is False
    assert result.reranked is None
    assert result.error_type == "TimeoutError"
    assert result.gate["reason"] == "rerank_execution_failed"
