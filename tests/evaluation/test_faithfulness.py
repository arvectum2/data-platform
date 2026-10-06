from __future__ import annotations

from pathlib import Path

from arvectum_data.evaluation.faithfulness import (
    _evaluate_answer,
    load_faithfulness_suite,
)
from arvectum_data.answers import AnswerClaim, GroundedAnswer


def _suite():
    return load_faithfulness_suite(
        Path(__file__).resolve().parents[2] / "benchmarks" / "faithfulness_v1.json"
    )


def test_repository_faithfulness_suite_is_valid() -> None:
    suite = _suite()
    assert suite.name == "faithfulness-v1"
    assert len(suite.cases) == 4


def test_faithfulness_evaluator_scores_exact_claim_citations() -> None:
    case = _suite().cases[0]
    answer = GroundedAnswer(
        answer="Цена — 1999 рублей.",
        claims=(AnswerClaim("Цена — 1999 рублей.", ("price-1",)),),
        contradictions=(),
        uncertainty=None,
        abstained=False,
    )

    result = _evaluate_answer(case, answer, latency_ms=10.0)

    assert result.passed is True
    assert result.citation_precision == 1.0
    assert result.citation_recall == 1.0
    assert result.claim_support_rate == 1.0


def test_faithfulness_evaluator_detects_incomplete_multisource_citation() -> None:
    case = next(
        item for item in _suite().cases
        if item.case_id == "multi-source-contract-supplier"
    )
    answer = GroundedAnswer(
        answer="ИНН — 7701234567.",
        claims=(
            AnswerClaim(
                "Поставщик Альфа имеет ИНН 7701234567.",
                ("supplier-1",),
            ),
        ),
        contradictions=(),
        uncertainty=None,
        abstained=False,
    )

    result = _evaluate_answer(case, answer, latency_ms=10.0)

    assert result.passed is False
    assert result.citation_precision == 1.0
    assert result.citation_recall == 0.5
    assert result.claim_support_rate == 0.5
