from __future__ import annotations

from dataclasses import dataclass

from .models import EvaluationSummary


@dataclass(frozen=True, slots=True)
class RerankGate:
    min_mrr_gain: float = 0.01
    min_top1_gain: float = 0.0
    max_p95_latency_multiplier: float = 3.0

    def evaluate(
        self,
        baseline: EvaluationSummary,
        reranked: EvaluationSummary,
    ) -> dict[str, object]:
        if baseline.suite_name != reranked.suite_name:
            raise ValueError("baseline and reranked summaries must use the same suite")
        mrr_gain = reranked.mrr - baseline.mrr
        top1_gain = reranked.top1_accuracy - baseline.top1_accuracy
        if baseline.latency_p95_ms <= 0:
            latency_multiplier = 1.0
        else:
            latency_multiplier = reranked.latency_p95_ms / baseline.latency_p95_ms
        passed = (
            mrr_gain >= self.min_mrr_gain
            and top1_gain >= self.min_top1_gain
            and latency_multiplier <= self.max_p95_latency_multiplier
        )
        return {
            "passed": passed,
            "mrr_gain": round(mrr_gain, 6),
            "top1_gain": round(top1_gain, 6),
            "p95_latency_multiplier": round(latency_multiplier, 4),
            "thresholds": {
                "min_mrr_gain": self.min_mrr_gain,
                "min_top1_gain": self.min_top1_gain,
                "max_p95_latency_multiplier": self.max_p95_latency_multiplier,
            },
        }
