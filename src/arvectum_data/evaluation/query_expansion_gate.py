from __future__ import annotations

from dataclasses import dataclass

from .models import EvaluationSummary


@dataclass(frozen=True, slots=True)
class QueryExpansionGate:
    min_mrr_gain: float = 0.01
    min_recall_at_5_gain: float = 0.01
    max_p95_latency_multiplier: float = 2.0

    def evaluate(
        self,
        baseline: EvaluationSummary,
        expanded: EvaluationSummary,
    ) -> dict[str, object]:
        if baseline.suite_name != expanded.suite_name:
            raise ValueError("baseline and expanded summaries must use the same suite")
        mrr_gain = expanded.mrr - baseline.mrr
        recall_gain = expanded.mean_recall_at_5 - baseline.mean_recall_at_5
        latency_multiplier = (
            1.0
            if baseline.latency_p95_ms <= 0
            else expanded.latency_p95_ms / baseline.latency_p95_ms
        )
        passed = (
            (mrr_gain >= self.min_mrr_gain or recall_gain >= self.min_recall_at_5_gain)
            and expanded.top1_accuracy >= baseline.top1_accuracy
            and latency_multiplier <= self.max_p95_latency_multiplier
        )
        return {
            "passed": passed,
            "mrr_gain": round(mrr_gain, 6),
            "recall_at_5_gain": round(recall_gain, 6),
            "top1_gain": round(expanded.top1_accuracy - baseline.top1_accuracy, 6),
            "p95_latency_multiplier": round(latency_multiplier, 4),
        }
