from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median
from typing import Any, Mapping, Sequence

from ..answers import GroundedAnswer, ReasoningAnswerSynthesizer
from ..models import ModelLocality, ModelRole
from ..models.providers import OpenAICompatibleProvider
from ..search import SearchEvidence, SearchHit, SearchScores
from .metrics import set_precision_recall


@dataclass(frozen=True, slots=True)
class FaithfulnessEvidence:
    chunk_id: str
    text: str

    def __post_init__(self) -> None:
        if not self.chunk_id.strip():
            raise ValueError("chunk_id must not be blank")
        if not self.text.strip():
            raise ValueError("evidence text must not be blank")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FaithfulnessEvidence":
        return cls(
            chunk_id=str(payload["chunk_id"]),
            text=str(payload["text"]),
        )


@dataclass(frozen=True, slots=True)
class RequiredClaim:
    terms: tuple[str, ...]
    expected_chunk_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.terms or any(not term.strip() for term in self.terms):
            raise ValueError("required claim terms must not be empty")
        if not self.expected_chunk_ids:
            raise ValueError("required claim expected_chunk_ids must not be empty")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RequiredClaim":
        return cls(
            terms=tuple(str(term) for term in payload["terms"]),
            expected_chunk_ids=tuple(str(item) for item in payload["expected_chunk_ids"]),
        )


@dataclass(frozen=True, slots=True)
class FaithfulnessCase:
    case_id: str
    query: str
    evidence: tuple[FaithfulnessEvidence, ...]
    expected_abstained: bool
    required_claims: tuple[RequiredClaim, ...] = ()
    required_contradiction_terms: tuple[str, ...] = ()
    required_answer_terms: tuple[str, ...] = ()
    max_claims: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.case_id.strip() or not self.query.strip():
            raise ValueError("case id and query must not be blank")
        if not self.evidence:
            raise ValueError("faithfulness case must contain evidence")
        evidence_ids = {item.chunk_id for item in self.evidence}
        if len(evidence_ids) != len(self.evidence):
            raise ValueError("evidence chunk IDs must be unique")
        for claim in self.required_claims:
            if not set(claim.expected_chunk_ids) <= evidence_ids:
                raise ValueError("required claim references unknown evidence")
        if self.max_claims is not None and self.max_claims < 0:
            raise ValueError("max_claims must be non-negative")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FaithfulnessCase":
        return cls(
            case_id=str(payload["id"]),
            query=str(payload["query"]),
            evidence=tuple(
                FaithfulnessEvidence.from_dict(item)
                for item in payload["evidence"]
            ),
            expected_abstained=bool(payload["expected_abstained"]),
            required_claims=tuple(
                RequiredClaim.from_dict(item)
                for item in payload.get("required_claims") or ()
            ),
            required_contradiction_terms=tuple(
                str(term)
                for term in payload.get("required_contradiction_terms") or ()
            ),
            required_answer_terms=tuple(
                str(term)
                for term in payload.get("required_answer_terms") or ()
            ),
            max_claims=(
                int(payload["max_claims"])
                if payload.get("max_claims") is not None
                else None
            ),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class FaithfulnessSuite:
    name: str
    cases: tuple[FaithfulnessCase, ...]
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FaithfulnessSuite":
        raw_cases = payload.get("cases")
        if not isinstance(raw_cases, Sequence) or isinstance(raw_cases, (str, bytes)):
            raise ValueError("cases must be a list")
        cases = tuple(FaithfulnessCase.from_dict(item) for item in raw_cases)
        if not cases:
            raise ValueError("suite must contain at least one case")
        ids = [case.case_id for case in cases]
        if len(ids) != len(set(ids)):
            raise ValueError("faithfulness case IDs must be unique")
        return cls(
            name=str(payload["name"]),
            description=str(payload.get("description") or ""),
            metadata=dict(payload.get("metadata") or {}),
            cases=cases,
        )


@dataclass(frozen=True, slots=True)
class FaithfulnessCaseResult:
    case_id: str
    passed: bool
    abstention_correct: bool
    citation_precision: float
    citation_recall: float
    claim_support_rate: float
    contradiction_recall: float
    answer_term_recall: float
    latency_ms: float
    answer: str | None
    abstained: bool
    error_type: str | None = None


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
class FaithfulnessSummary:
    suite_name: str
    cases: int
    pass_rate: float
    abstention_accuracy: float
    citation_precision: float
    citation_recall: float
    claim_support_rate: float
    contradiction_recall: float
    answer_term_recall: float
    latency_mean_ms: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_max_ms: float
    results: tuple[FaithfulnessCaseResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_name": self.suite_name,
            "cases": self.cases,
            "pass_rate": self.pass_rate,
            "abstention_accuracy": self.abstention_accuracy,
            "citation_precision": self.citation_precision,
            "citation_recall": self.citation_recall,
            "claim_support_rate": self.claim_support_rate,
            "contradiction_recall": self.contradiction_recall,
            "answer_term_recall": self.answer_term_recall,
            "latency_mean_ms": self.latency_mean_ms,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "latency_max_ms": self.latency_max_ms,
            "results": [
                {
                    "case_id": item.case_id,
                    "passed": item.passed,
                    "abstention_correct": item.abstention_correct,
                    "citation_precision": item.citation_precision,
                    "citation_recall": item.citation_recall,
                    "claim_support_rate": item.claim_support_rate,
                    "contradiction_recall": item.contradiction_recall,
                    "answer_term_recall": item.answer_term_recall,
                    "latency_ms": item.latency_ms,
                    "answer": item.answer,
                    "abstained": item.abstained,
                    "error_type": item.error_type,
                }
                for item in self.results
            ],
        }


def load_faithfulness_suite(path: Path) -> FaithfulnessSuite:
    return FaithfulnessSuite.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _hit(item: FaithfulnessEvidence) -> SearchHit:
    return SearchHit(
        chunk_id=item.chunk_id,
        document_id=f"document-{item.chunk_id}",
        resource_id=f"resource-{item.chunk_id}",
        canonical_uri=f"benchmark://faithfulness/{item.chunk_id}",
        title=f"Evidence {item.chunk_id}",
        preview=item.text,
        text=item.text,
        scores=SearchScores(1.0, 1.0, 1.0),
        evidence=(
            SearchEvidence(
                f"resource-{item.chunk_id}",
                f"document-{item.chunk_id}",
                item.chunk_id,
                f"benchmark://faithfulness/{item.chunk_id}",
            ),
        ),
        metadata={"collection_id": "benchmark:faithfulness"},
    )


def _evaluate_answer(
    case: FaithfulnessCase,
    answer: GroundedAnswer,
    *,
    latency_ms: float,
) -> FaithfulnessCaseResult:
    evidence_by_id = {item.chunk_id: item.text for item in case.evidence}
    abstention_correct = answer.abstained == case.expected_abstained
    if case.max_claims is not None:
        abstention_correct = abstention_correct and len(answer.claims) <= case.max_claims

    expected_citations: set[str] = set()
    actual_citations: set[str] = set()
    support_checks: list[bool] = []

    for required in case.required_claims:
        expected_citations.update(required.expected_chunk_ids)
        matching = next(
            (
                claim
                for claim in answer.claims
                if all(term.lower() in claim.text.lower() for term in required.terms)
            ),
            None,
        )
        if matching is None:
            support_checks.append(False)
            continue

        actual_citations.update(matching.chunk_ids)
        cited_text = " ".join(
            evidence_by_id[chunk_id]
            for chunk_id in matching.chunk_ids
            if chunk_id in evidence_by_id
        ).lower()
        support_checks.append(
            all(term.lower() in cited_text for term in required.terms)
            and set(required.expected_chunk_ids) <= set(matching.chunk_ids)
        )

    if not case.required_claims:
        citation_precision = 1.0
        citation_recall = 1.0
        claim_support_rate = 1.0
    else:
        citation_precision, citation_recall = set_precision_recall(
            tuple(expected_citations),
            tuple(actual_citations),
        )
        claim_support_rate = mean(1.0 if item else 0.0 for item in support_checks)

    answer_text = (answer.answer or "").lower()
    if case.required_answer_terms:
        matched_answer_terms = sum(
            1 for term in case.required_answer_terms if term.lower() in answer_text
        )
        answer_term_recall = matched_answer_terms / len(case.required_answer_terms)
    else:
        answer_term_recall = 1.0

    contradiction_text = " ".join(answer.contradictions).lower()
    if case.required_contradiction_terms:
        matched = sum(
            1
            for term in case.required_contradiction_terms
            if term.lower() in contradiction_text
        )
        contradiction_recall = matched / len(case.required_contradiction_terms)
    else:
        contradiction_recall = 1.0

    passed = (
        abstention_correct
        and citation_precision == 1.0
        and citation_recall == 1.0
        and claim_support_rate == 1.0
        and contradiction_recall == 1.0
        and answer_term_recall == 1.0
    )
    return FaithfulnessCaseResult(
        case_id=case.case_id,
        passed=passed,
        abstention_correct=abstention_correct,
        citation_precision=citation_precision,
        citation_recall=citation_recall,
        claim_support_rate=claim_support_rate,
        contradiction_recall=contradiction_recall,
        answer_term_recall=answer_term_recall,
        latency_ms=latency_ms,
        answer=answer.answer,
        abstained=answer.abstained,
    )


def evaluate_faithfulness_suite(
    suite: FaithfulnessSuite,
    provider: OpenAICompatibleProvider,
) -> FaithfulnessSummary:
    results: list[FaithfulnessCaseResult] = []
    for case in suite.cases:
        started = time.perf_counter()
        try:
            answer = ReasoningAnswerSynthesizer(
                provider,
                max_hits=len(case.evidence),
            ).synthesize(
                case.query,
                [_hit(item) for item in case.evidence],
            )
            latency_ms = (time.perf_counter() - started) * 1000.0
            result = _evaluate_answer(case, answer, latency_ms=latency_ms)
        except Exception as exc:
            latency_ms = (time.perf_counter() - started) * 1000.0
            result = FaithfulnessCaseResult(
                case_id=case.case_id,
                passed=False,
                abstention_correct=False,
                citation_precision=0.0,
                citation_recall=0.0,
                claim_support_rate=0.0,
                contradiction_recall=0.0,
                answer_term_recall=0.0,
                latency_ms=latency_ms,
                answer=None,
                abstained=True,
                error_type=type(exc).__name__,
            )
        results.append(result)

    latencies = [item.latency_ms for item in results]
    return FaithfulnessSummary(
        suite_name=suite.name,
        cases=len(results),
        pass_rate=mean(1.0 if item.passed else 0.0 for item in results),
        abstention_accuracy=mean(
            1.0 if item.abstention_correct else 0.0 for item in results
        ),
        citation_precision=mean(item.citation_precision for item in results),
        citation_recall=mean(item.citation_recall for item in results),
        claim_support_rate=mean(item.claim_support_rate for item in results),
        contradiction_recall=mean(item.contradiction_recall for item in results),
        answer_term_recall=mean(item.answer_term_recall for item in results),
        latency_mean_ms=mean(latencies),
        latency_p50_ms=median(latencies),
        latency_p95_ms=_percentile(latencies, 0.95),
        latency_max_ms=max(latencies),
        results=tuple(results),
    )


def build_local_provider(
    *,
    model: str,
    base_url: str,
    version: str | None = None,
    timeout_seconds: float = 75,
) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        role=ModelRole.REASONING,
        model=model,
        base_url=base_url,
        locality=ModelLocality.LOCAL,
        version=version,
        timeout_seconds=timeout_seconds,
        retry_max_attempts=1,
        retry_base_delay_seconds=0,
        max_concurrency=1,
    )
