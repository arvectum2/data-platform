from __future__ import annotations

import json
from pathlib import Path

import pytest

from arvectum_data.evaluation import (
    EvaluationCase,
    EvaluationSuite,
    evaluate_case,
    evaluate_suite,
)
from arvectum_data.evaluation.cli import main
from arvectum_data.evaluation.http_runner import (
    EvaluationRequestError,
    HttpSearchRunner,
)


def test_evaluate_case_supports_chunk_identity_and_recall() -> None:
    case = EvaluationCase(
        case_id="tender-payment",
        query="payment",
        collections=("tender:1",),
        expected_ids=("chunk-good", "chunk-also-good"),
        id_field="chunk_id",
        limit=5,
    )

    result = evaluate_case(
        case,
        hits=[
            {"chunk_id": "chunk-other"},
            {"chunk_id": "chunk-good"},
            {"chunk_id": "chunk-also-good"},
        ],
        latency_ms=12.5,
    )

    assert result.rank == 2
    assert result.reciprocal_rank == pytest.approx(0.5)
    assert result.top1 is False
    assert result.hit_at_3 is True
    assert result.hit_at_5 is True
    assert result.recall_at_5 == pytest.approx(1.0)
    assert result.ndcg_at_5 > 0.0
    assert result.latency_ms == pytest.approx(12.5)


def test_evaluate_suite_aggregates_quality_and_latency() -> None:
    suite = EvaluationSuite(
        name="sample",
        cases=(
            EvaluationCase(
                case_id="one",
                query="one",
                collections=("collection",),
                expected_ids=("https://example.com/one",),
            ),
            EvaluationCase(
                case_id="two",
                query="two",
                collections=("collection",),
                expected_ids=("https://example.com/two",),
            ),
        ),
    )

    responses = {
        "one": (
            [
                {"canonical_uri": "https://example.com/one"},
                {"canonical_uri": "https://example.com/other"},
            ],
            100.0,
        ),
        "two": (
            [
                {"canonical_uri": "https://example.com/other"},
                {"canonical_uri": "https://example.com/two"},
            ],
            300.0,
        ),
    }

    summary = evaluate_suite(suite, lambda case: responses[case.case_id])

    assert summary.cases == 2
    assert summary.top1_accuracy == pytest.approx(0.5)
    assert summary.mrr == pytest.approx(0.75)
    assert summary.hit_rate_at_3 == pytest.approx(1.0)
    assert summary.hit_rate_at_5 == pytest.approx(1.0)
    assert summary.mean_recall_at_5 == pytest.approx(1.0)
    assert summary.mean_ndcg_at_5 > 0.0
    assert summary.latency_p50_ms == pytest.approx(200.0)
    assert summary.latency_p95_ms == pytest.approx(290.0)
    assert summary.latency_max_ms == pytest.approx(300.0)


def test_suite_from_dict_applies_defaults_and_case_overrides() -> None:
    suite = EvaluationSuite.from_dict(
        {
            "name": "defaults",
            "defaults": {
                "collections": ["default:collection"],
                "id_field": "chunk_id",
                "mode": "hybrid",
                "lexical_weight": 1,
                "vector_weight": 4,
                "limit": 5,
            },
            "cases": [
                {
                    "id": "default-case",
                    "query": "default",
                    "expected_ids": ["chunk-1"],
                },
                {
                    "id": "override-case",
                    "query": "override",
                    "collections": ["other:collection"],
                    "expected_ids": ["https://example.com"],
                    "id_field": "canonical_uri",
                    "vector_weight": 1,
                },
            ],
        }
    )

    first, second = suite.cases
    assert first.collections == ("default:collection",)
    assert first.id_field == "chunk_id"
    assert first.vector_weight == 4
    assert first.limit == 5
    assert second.collections == ("other:collection",)
    assert second.id_field == "canonical_uri"
    assert second.vector_weight == 1


def test_suite_rejects_duplicate_case_ids() -> None:
    case = EvaluationCase(
        case_id="duplicate",
        query="q",
        collections=("c",),
        expected_ids=("x",),
    )
    with pytest.raises(ValueError, match="unique"):
        EvaluationSuite(name="bad", cases=(case, case))


def test_graded_relevance_drives_ndcg() -> None:
    case = EvaluationCase(
        case_id="graded",
        query="q",
        collections=("c",),
        expected_ids=("best", "good"),
        relevance={"best": 3.0, "good": 1.0},
    )

    ideal = evaluate_case(
        case,
        hits=[{"canonical_uri": "best"}, {"canonical_uri": "good"}],
        latency_ms=1.0,
    )
    reversed_order = evaluate_case(
        case,
        hits=[{"canonical_uri": "good"}, {"canonical_uri": "best"}],
        latency_ms=1.0,
    )

    assert ideal.ndcg_at_5 == pytest.approx(1.0)
    assert reversed_order.ndcg_at_5 < ideal.ndcg_at_5


def test_cli_thresholds_can_fail_ci(monkeypatch, tmp_path) -> None:
    benchmark = tmp_path / "benchmark.json"
    benchmark.write_text(
        json.dumps(
            {
                "name": "cli",
                "cases": [
                    {
                        "id": "case-1",
                        "query": "query",
                        "collections": ["one"],
                        "expected_ids": ["expected"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    class FakeRunner:
        def __init__(self, **kwargs):
            pass

        def __call__(self, case):
            return ([{"canonical_uri": "not-expected"}], 10.0)

    monkeypatch.setattr("arvectum_data.evaluation.cli.HttpSearchRunner", FakeRunner)

    assert (
        main(
            [
                str(benchmark),
                "--fail-top1-below",
                "1.0",
            ]
        )
        == 2
    )


def test_http_runner_requires_complete_consumer_credentials() -> None:
    case = EvaluationCase(
        case_id="federated",
        query="photo size",
        collections=("site", "products"),
        expected_ids=("expected",),
    )
    runner = HttpSearchRunner(
        base_url="http://127.0.0.1:9",
        consumer="growth-agent",
        consumer_key="",
        timeout_seconds=0.01,
    )

    with pytest.raises(EvaluationRequestError, match="configured together"):
        runner(case)


def test_cli_passes_consumer_credentials(monkeypatch, tmp_path) -> None:
    benchmark = tmp_path / "benchmark.json"
    benchmark.write_text(
        json.dumps(
            {
                "name": "consumer-cli",
                "cases": [
                    {
                        "id": "case-1",
                        "query": "query",
                        "collections": ["one"],
                        "expected_ids": ["expected"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    captured = {}

    class FakeRunner:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def __call__(self, case):
            return ([{"canonical_uri": "expected"}], 5.0)

    monkeypatch.setattr("arvectum_data.evaluation.cli.HttpSearchRunner", FakeRunner)
    monkeypatch.setenv("TEST_CONSUMER_KEY", "scoped-secret")

    assert (
        main(
            [
                str(benchmark),
                "--consumer",
                "growth-agent",
                "--consumer-key-env",
                "TEST_CONSUMER_KEY",
            ]
        )
        == 0
    )
    assert captured["consumer"] == "growth-agent"
    assert captured["consumer_key"] == "scoped-secret"


@pytest.mark.parametrize(
    ("filename", "expected_cases"),
    [
        ("production_acceptance_v1.json", 9),
        ("production_acceptance_v2.json", 10),
        ("production_acceptance_v3.json", 20),
        ("growth_search_console_v1.json", 12),
        ("lexical_exact_v1.json", 5),
    ],
)
def test_repository_benchmarks_are_valid_frozen_suites(
    filename: str,
    expected_cases: int,
) -> None:
    benchmark = Path(__file__).resolve().parents[2] / "benchmarks" / filename
    suite = EvaluationSuite.from_dict(json.loads(benchmark.read_text(encoding="utf-8")))

    assert len(suite.cases) == expected_cases
    assert len({case.case_id for case in suite.cases}) == expected_cases


def test_production_acceptance_v3_contains_real_consumer_evidence() -> None:
    benchmark = (
        Path(__file__).resolve().parents[2]
        / "benchmarks"
        / "production_acceptance_v3.json"
    )
    suite = EvaluationSuite.from_dict(json.loads(benchmark.read_text(encoding="utf-8")))

    new_cases = suite.cases[-10:]
    assert {case.metadata.get("consumer") for case in new_cases} == {
        "growth",
        "tender-agent",
    }
    assert all(
        case.metadata.get("accepted_into_production_suite") == "2026-10-05"
        for case in new_cases
    )
