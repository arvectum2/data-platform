from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class OperationSLO:
    p95_latency_ms: int
    max_error_rate: float = 0.01
    min_samples: int = 20


OPERATION_SLOS: Mapping[str, OperationSLO] = {
    "process": OperationSLO(10_000),
    "ingest": OperationSLO(10_000),
    "search": OperationSLO(1_500),
    "answer": OperationSLO(20_000),
    "research": OperationSLO(120_000),
    "discover": OperationSLO(5_000),
    "extract": OperationSLO(10_000),
    "reindex": OperationSLO(120_000),
}


def percentile(values: Sequence[int], quantile: float) -> int:
    if not values:
        return 0
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be between 0 and 1")
    ordered = sorted(int(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return int(round(ordered[lower] * (1 - fraction) + ordered[upper] * fraction))


def evaluate_operation_slo(
    *,
    operation: str,
    requests: int,
    errors: int,
    latency_samples_ms: Sequence[int],
) -> dict[str, object]:
    slo = OPERATION_SLOS[operation]
    samples = len(latency_samples_ms)
    p95_ms = percentile(latency_samples_ms, 0.95)
    error_rate = (errors / requests) if requests else 0.0
    enough_samples = samples >= slo.min_samples

    if not enough_samples:
        status = "insufficient-data"
    elif p95_ms <= slo.p95_latency_ms and error_rate <= slo.max_error_rate:
        status = "green"
    else:
        status = "red"

    return {
        "status": status,
        "requests": requests,
        "errors": errors,
        "window_samples": samples,
        "p95_ms": p95_ms,
        "error_rate": error_rate,
        "targets": {
            "p95_latency_ms": slo.p95_latency_ms,
            "max_error_rate": slo.max_error_rate,
            "min_samples": slo.min_samples,
        },
    }


def overall_readiness(operations: Mapping[str, Mapping[str, object]]) -> str:
    statuses = {str(item.get("status")) for item in operations.values()}
    if "red" in statuses:
        return "red"
    if "green" in statuses:
        return "green"
    return "insufficient-data"
