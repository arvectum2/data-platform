from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Sequence


ResultIdField = Literal["canonical_uri", "chunk_id", "document_id", "resource_id"]


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    case_id: str
    query: str
    collections: tuple[str, ...]
    expected_ids: tuple[str, ...]
    id_field: ResultIdField = "canonical_uri"
    limit: int = 10
    mode: str = "hybrid"
    lexical_weight: float = 1.0
    vector_weight: float = 1.0
    query_variants: tuple[str, ...] = ()
    query_variant_weight: float = 0.5
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id must not be blank")
        if not self.query.strip():
            raise ValueError("query must not be blank")
        if not self.collections:
            raise ValueError("collections must not be empty")
        if not self.expected_ids:
            raise ValueError("expected_ids must not be empty")
        if self.id_field not in {
            "canonical_uri",
            "chunk_id",
            "document_id",
            "resource_id",
        }:
            raise ValueError(f"unsupported id_field: {self.id_field}")
        if self.limit < 1 or self.limit > 100:
            raise ValueError("limit must be between 1 and 100")
        if self.lexical_weight < 0 or self.vector_weight < 0:
            raise ValueError("fusion weights must be non-negative")
        if self.query_variant_weight < 0 or self.query_variant_weight > 1:
            raise ValueError("query_variant_weight must be between 0 and 1")
        if len(self.query_variants) > 8:
            raise ValueError("at most 8 query variants are allowed")

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        defaults: Mapping[str, Any] | None = None,
    ) -> "EvaluationCase":
        merged = dict(defaults or {})
        merged.update(dict(payload))
        return cls(
            case_id=str(merged["id"]),
            query=str(merged["query"]),
            collections=tuple(str(item) for item in merged["collections"]),
            expected_ids=tuple(str(item) for item in merged["expected_ids"]),
            id_field=str(merged.get("id_field", "canonical_uri")),  # type: ignore[arg-type]
            limit=int(merged.get("limit", 10)),
            mode=str(merged.get("mode", "hybrid")),
            lexical_weight=float(merged.get("lexical_weight", 1.0)),
            vector_weight=float(merged.get("vector_weight", 1.0)),
            query_variants=tuple(
                str(item) for item in (merged.get("query_variants") or ())
            ),
            query_variant_weight=float(
                merged.get("query_variant_weight", 0.5)
            ),
            metadata=dict(merged.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class EvaluationSuite:
    name: str
    cases: tuple[EvaluationCase, ...]
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("suite name must not be blank")
        if not self.cases:
            raise ValueError("suite must contain at least one case")
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("evaluation case IDs must be unique")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EvaluationSuite":
        defaults = dict(payload.get("defaults") or {})
        raw_cases = payload.get("cases")
        if not isinstance(raw_cases, Sequence) or isinstance(raw_cases, (str, bytes)):
            raise ValueError("cases must be a list")
        return cls(
            name=str(payload["name"]),
            description=str(payload.get("description") or ""),
            metadata=dict(payload.get("metadata") or {}),
            cases=tuple(
                EvaluationCase.from_dict(item, defaults=defaults)
                for item in raw_cases
            ),
        )


@dataclass(frozen=True, slots=True)
class CaseEvaluation:
    case_id: str
    rank: int | None
    reciprocal_rank: float
    top1: bool
    hit_at_3: bool
    hit_at_5: bool
    recall_at_5: float
    latency_ms: float
    returned_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvaluationSummary:
    suite_name: str
    cases: int
    top1_accuracy: float
    mrr: float
    hit_rate_at_3: float
    hit_rate_at_5: float
    mean_recall_at_5: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_max_ms: float
    case_results: tuple[CaseEvaluation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_name": self.suite_name,
            "cases": self.cases,
            "top1_accuracy": self.top1_accuracy,
            "mrr": self.mrr,
            "hit_rate_at_3": self.hit_rate_at_3,
            "hit_rate_at_5": self.hit_rate_at_5,
            "mean_recall_at_5": self.mean_recall_at_5,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "latency_max_ms": self.latency_max_ms,
            "case_results": [
                {
                    "case_id": item.case_id,
                    "rank": item.rank,
                    "reciprocal_rank": item.reciprocal_rank,
                    "top1": item.top1,
                    "hit_at_3": item.hit_at_3,
                    "hit_at_5": item.hit_at_5,
                    "recall_at_5": item.recall_at_5,
                    "latency_ms": item.latency_ms,
                    "returned_ids": list(item.returned_ids),
                }
                for item in self.case_results
            ],
        }
