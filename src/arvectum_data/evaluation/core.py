from __future__ import annotations

from collections.abc import Callable, Sequence
from statistics import mean, median
from typing import Any

from .models import (
    CaseEvaluation,
    EvaluationCase,
    EvaluationSuite,
    EvaluationSummary,
)


SearchRunner = Callable[[EvaluationCase], tuple[Sequence[dict[str, Any]], float]]


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def evaluate_case(
    case: EvaluationCase,
    *,
    hits: Sequence[dict[str, Any]],
    latency_ms: float,
) -> CaseEvaluation:
    returned_ids = tuple(
        str(hit.get(case.id_field, ""))
        for hit in hits
        if hit.get(case.id_field) is not None
    )
    expected = set(case.expected_ids)

    first_rank = next(
        (
            rank
            for rank, result_id in enumerate(returned_ids, start=1)
            if result_id in expected
        ),
        None,
    )
    reciprocal_rank = 0.0 if first_rank is None else 1.0 / first_rank
    top5 = returned_ids[:5]
    recall_at_5 = len(expected.intersection(top5)) / len(expected)

    return CaseEvaluation(
        case_id=case.case_id,
        rank=first_rank,
        reciprocal_rank=reciprocal_rank,
        top1=first_rank == 1,
        hit_at_3=first_rank is not None and first_rank <= 3,
        hit_at_5=first_rank is not None and first_rank <= 5,
        recall_at_5=recall_at_5,
        latency_ms=float(latency_ms),
        returned_ids=returned_ids,
    )


def evaluate_suite(
    suite: EvaluationSuite,
    runner: SearchRunner,
) -> EvaluationSummary:
    results = []
    for case in suite.cases:
        hits, latency_ms = runner(case)
        results.append(
            evaluate_case(
                case,
                hits=hits,
                latency_ms=latency_ms,
            )
        )

    latencies = [item.latency_ms for item in results]
    count = len(results)
    return EvaluationSummary(
        suite_name=suite.name,
        cases=count,
        top1_accuracy=mean(1.0 if item.top1 else 0.0 for item in results),
        mrr=mean(item.reciprocal_rank for item in results),
        hit_rate_at_3=mean(1.0 if item.hit_at_3 else 0.0 for item in results),
        hit_rate_at_5=mean(1.0 if item.hit_at_5 else 0.0 for item in results),
        mean_recall_at_5=mean(item.recall_at_5 for item in results),
        latency_p50_ms=median(latencies),
        latency_p95_ms=_percentile(latencies, 0.95),
        latency_max_ms=max(latencies, default=0.0),
        case_results=tuple(results),
    )
