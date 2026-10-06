from __future__ import annotations

from pathlib import Path

from arvectum_data.evaluation.facts import (
    evaluate_fact_chunking,
    load_fact_suite,
)


def _suite_path() -> Path:
    return Path(__file__).resolve().parents[2] / "benchmarks" / "fact_preservation_v1.json"


def test_repository_fact_suite_is_valid() -> None:
    suite = load_fact_suite(_suite_path())

    assert suite.name == "fact-preservation-v1"
    assert len(suite.cases) == 6
    assert {case.kind for case in suite.cases} == {
        "identifier",
        "date",
        "amount",
    }


def test_default_chunking_preserves_exact_facts_with_context() -> None:
    summary = evaluate_fact_chunking(load_fact_suite(_suite_path()))

    assert summary.cases == 6
    assert summary.chunk_preservation_rate == 1.0
    assert summary.context_preservation_rate == 1.0
    assert summary.retrieval_top1_rate is None
    assert all(item.chunk_passed for item in summary.results)
