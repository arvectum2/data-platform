from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..documents.ocr import OCRDocumentResult, OCRPageResult
from ..documents.vlm import pages_requiring_vlm


@dataclass(frozen=True, slots=True)
class VLMRoutingCase:
    case_id: str
    artifact_id: str
    ocr_profile: str
    ocr_text_chars: int
    ocr_confidence: float | None
    expected_escalation: bool
    expected_reason: str | None = None
    cer: float | None = None
    wer: float | None = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "VLMRoutingCase":
        return cls(
            case_id=str(payload["id"]),
            artifact_id=str(payload["artifact_id"]),
            ocr_profile=str(payload["ocr_profile"]),
            ocr_text_chars=int(payload["ocr_text_chars"]),
            ocr_confidence=(
                float(payload["ocr_confidence"])
                if payload.get("ocr_confidence") is not None
                else None
            ),
            expected_escalation=bool(payload["expected_escalation"]),
            expected_reason=(
                str(payload["expected_reason"])
                if payload.get("expected_reason")
                else None
            ),
            cer=float(payload["cer"]) if payload.get("cer") is not None else None,
            wer=float(payload["wer"]) if payload.get("wer") is not None else None,
        )


@dataclass(frozen=True, slots=True)
class VLMRoutingSuite:
    name: str
    min_ocr_confidence: float
    min_ocr_chars: int
    cases: tuple[VLMRoutingCase, ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "VLMRoutingSuite":
        metadata = dict(payload.get("metadata") or {})
        raw_cases = payload.get("cases")
        if not isinstance(raw_cases, Sequence) or isinstance(raw_cases, (str, bytes)):
            raise ValueError("cases must be a list")
        return cls(
            name=str(payload["name"]),
            min_ocr_confidence=float(metadata.get("min_ocr_confidence", 90.0)),
            min_ocr_chars=int(metadata.get("min_ocr_chars", 24)),
            cases=tuple(VLMRoutingCase.from_dict(item) for item in raw_cases),
        )


def load_vlm_routing_suite(path: Path) -> VLMRoutingSuite:
    return VLMRoutingSuite.from_dict(json.loads(path.read_text(encoding="utf-8")))


def evaluate_vlm_routing_suite(suite: VLMRoutingSuite) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    correct = 0
    for index, case in enumerate(suite.cases, start=1):
        page = OCRPageResult(
            page_number=index,
            text="x" * case.ocr_text_chars,
            confidence=case.ocr_confidence,
            provider="recorded-tesseract",
        )
        escalations = pages_requiring_vlm(
            OCRDocumentResult((page,), "recorded-tesseract"),
            min_ocr_confidence=suite.min_ocr_confidence,
            min_ocr_chars=suite.min_ocr_chars,
        )
        actual_escalation = bool(escalations)
        actual_reason = escalations[0][1] if escalations else None
        passed = (
            actual_escalation == case.expected_escalation
            and (
                case.expected_reason is None
                or actual_reason == case.expected_reason
            )
        )
        correct += int(passed)
        observations.append(
            {
                "case_id": case.case_id,
                "artifact_id": case.artifact_id,
                "ocr_profile": case.ocr_profile,
                "ocr_confidence": case.ocr_confidence,
                "ocr_text_chars": case.ocr_text_chars,
                "cer": case.cer,
                "wer": case.wer,
                "expected_escalation": case.expected_escalation,
                "actual_escalation": actual_escalation,
                "expected_reason": case.expected_reason,
                "actual_reason": actual_reason,
                "passed": passed,
            }
        )
    total = len(suite.cases)
    return {
        "suite_name": suite.name,
        "cases": total,
        "correct": correct,
        "routing_accuracy": correct / total if total else 0.0,
        "min_ocr_confidence": suite.min_ocr_confidence,
        "min_ocr_chars": suite.min_ocr_chars,
        "observations": observations,
    }
