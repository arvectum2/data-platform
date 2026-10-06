from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .core import SearchRunner, evaluate_suite
from .models import EvaluationSuite, EvaluationSummary
from .rerank_gate import RerankGate


@dataclass(frozen=True, slots=True)
class RerankComparison:
    baseline: EvaluationSummary
    reranked: EvaluationSummary | None
    gate: dict[str, object]
    error_type: str | None = None

    @property
    def passed(self) -> bool:
        return bool(self.gate.get("passed", False))

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "error_type": self.error_type,
            "baseline": self.baseline.to_dict(),
            "reranked": None if self.reranked is None else self.reranked.to_dict(),
            "gate": dict(self.gate),
        }


def compare_reranking(
    suite: EvaluationSuite,
    *,
    baseline_runner: SearchRunner,
    reranked_runner: SearchRunner,
    gate: RerankGate | None = None,
) -> RerankComparison:
    active_gate = gate or RerankGate()
    baseline = evaluate_suite(suite, baseline_runner)
    try:
        reranked = evaluate_suite(suite, reranked_runner)
    except Exception as exc:
        return RerankComparison(
            baseline=baseline,
            reranked=None,
            gate={
                "passed": False,
                "reason": "rerank_execution_failed",
                "thresholds": {
                    "min_mrr_gain": active_gate.min_mrr_gain,
                    "min_top1_gain": active_gate.min_top1_gain,
                    "max_p95_latency_multiplier": active_gate.max_p95_latency_multiplier,
                },
            },
            error_type=type(exc).__name__,
        )
    return RerankComparison(
        baseline=baseline,
        reranked=reranked,
        gate=active_gate.evaluate(baseline, reranked),
    )
