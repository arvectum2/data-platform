from __future__ import annotations

from pathlib import Path

from arvectum_data.evaluation.adversarial import (
    AdversarialObservation,
    evaluate_adversarial_suite,
    load_adversarial_suite,
)


def _suite_path() -> Path:
    return Path(__file__).resolve().parents[2] / "benchmarks" / "adversarial_v1.json"


def test_repository_adversarial_suite_is_frozen_and_complete() -> None:
    suite = load_adversarial_suite(_suite_path())

    assert suite.name == "adversarial-v1"
    assert len(suite.cases) == 5
    assert {case.kind for case in suite.cases} == {
        "collection_isolation",
        "tenant_isolation",
        "duplicate_content",
        "conflicting_evidence",
        "stale_source",
    }


def test_adversarial_summary_fails_closed_on_runner_error() -> None:
    suite = load_adversarial_suite(_suite_path())

    def runner(case):
        if case.kind == "stale_source":
            raise RuntimeError("synthetic")
        return AdversarialObservation(
            case_id=case.case_id,
            kind=case.kind,
            passed=True,
        )

    summary = evaluate_adversarial_suite(suite, runner)

    assert summary.cases == 5
    assert summary.passed == 4
    assert summary.pass_rate == 0.8
    assert summary.all_passed is False
    failed = next(item for item in summary.observations if not item.passed)
    assert failed.kind == "stale_source"
    assert failed.details == {"error_type": "RuntimeError"}
