from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence


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


@dataclass(frozen=True, slots=True)
class StageLatency:
    stage: str
    samples: int
    p50_ms: float
    p95_ms: float
    max_ms: float

    @classmethod
    def from_values(cls, stage: str, values: Sequence[float]) -> "StageLatency":
        if not values:
            raise ValueError(f"stage {stage!r} has no latency samples")
        normalized = tuple(float(value) for value in values)
        return cls(
            stage=stage,
            samples=len(normalized),
            p50_ms=median(normalized),
            p95_ms=_percentile(normalized, 0.95),
            max_ms=max(normalized),
        )

    @classmethod
    def from_summary(
        cls,
        stage: str,
        *,
        samples: int,
        p50_ms: float,
        p95_ms: float,
        max_ms: float,
    ) -> "StageLatency":
        if samples < 1:
            raise ValueError(f"stage {stage!r} must have at least one sample")
        if min(p50_ms, p95_ms, max_ms) < 0:
            raise ValueError("latency values must be non-negative")
        if p50_ms > p95_ms or p95_ms > max_ms:
            raise ValueError("latency summary must satisfy p50 <= p95 <= max")
        return cls(stage, samples, float(p50_ms), float(p95_ms), float(max_ms))

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "samples": self.samples,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "max_ms": self.max_ms,
        }


@dataclass(frozen=True, slots=True)
class PipelineLatencyReport:
    stages: tuple[StageLatency, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"stages": [stage.to_dict() for stage in self.stages]}


def build_pipeline_latency_report(
    *,
    corpus: Mapping[str, Any],
    retrieval: Mapping[str, Any],
    faithfulness: Mapping[str, Any],
) -> PipelineLatencyReport:
    corpus_results = tuple(corpus.get("results") or ())
    native = [
        float(item["latency_ms"])
        for item in corpus_results
        if not item.get("skipped") and item.get("format") != "scanned-pdf"
    ]
    ocr = [
        float(item["latency_ms"])
        for item in corpus_results
        if not item.get("skipped") and item.get("format") == "scanned-pdf"
    ]
    retrieval_values = [
        float(item["latency_ms"])
        for item in retrieval.get("case_results") or ()
    ]
    synthesis = [
        float(item["latency_ms"])
        for item in faithfulness.get("results") or ()
    ]
    retrieval_stage = (
        StageLatency.from_values("retrieval", retrieval_values)
        if retrieval_values
        else StageLatency.from_summary(
            "retrieval",
            samples=int(retrieval["cases"]),
            p50_ms=float(retrieval["latency_p50_ms"]),
            p95_ms=float(retrieval["latency_p95_ms"]),
            max_ms=float(retrieval["latency_max_ms"]),
        )
    )
    synthesis_stage = (
        StageLatency.from_values("synthesis", synthesis)
        if synthesis
        else StageLatency.from_summary(
            "synthesis",
            samples=int(faithfulness["cases"]),
            p50_ms=float(faithfulness["latency_p50_ms"]),
            p95_ms=float(faithfulness["latency_p95_ms"]),
            max_ms=float(faithfulness["latency_max_ms"]),
        )
    )
    return PipelineLatencyReport(
        stages=(
            StageLatency.from_values("native_ingestion", native),
            StageLatency.from_values("ocr_ingestion", ocr),
            retrieval_stage,
            synthesis_stage,
        )
    )


def load_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload
