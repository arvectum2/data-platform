from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .core import SearchRunner, evaluate_suite
from .models import EvaluationSuite, EvaluationSummary
from .query_expansion_gate import QueryExpansionGate


@dataclass(frozen=True, slots=True)
class QueryExpansionComparison:
    baseline: EvaluationSummary
    expanded: EvaluationSummary | None
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
            "expanded": None if self.expanded is None else self.expanded.to_dict(),
            "gate": dict(self.gate),
        }


def compare_query_expansion(
    suite: EvaluationSuite,
    *,
    baseline_runner: SearchRunner,
    expanded_runner: SearchRunner,
    gate: QueryExpansionGate | None = None,
) -> QueryExpansionComparison:
    active_gate = gate or QueryExpansionGate()
    baseline = evaluate_suite(suite, baseline_runner)
    try:
        expanded = evaluate_suite(suite, expanded_runner)
    except Exception as exc:
        return QueryExpansionComparison(
            baseline=baseline,
            expanded=None,
            gate={
                "passed": False,
                "reason": "query_expansion_execution_failed",
                "thresholds": {
                    "min_mrr_gain": active_gate.min_mrr_gain,
                    "min_recall_at_5_gain": active_gate.min_recall_at_5_gain,
                    "max_p95_latency_multiplier": (
                        active_gate.max_p95_latency_multiplier
                    ),
                },
            },
            error_type=type(exc).__name__,
        )
    return QueryExpansionComparison(
        baseline=baseline,
        expanded=expanded,
        gate=active_gate.evaluate(baseline, expanded),
    )
