from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any

from pypdf import PdfReader

from ..documents.ocr import OCRProvider
from .corpus import _normalize_for_ocr
from .metrics import character_error_rate, word_error_rate


@dataclass(frozen=True, slots=True)
class PrivateOCRArtifact:
    artifact_id: str
    sha256: str
    category: str


@dataclass(frozen=True, slots=True)
class PrivateOCRSuite:
    name: str
    page: int
    artifacts: tuple[PrivateOCRArtifact, ...]
    poor_cer_above: float
    poor_wer_above: float
    vlm_confidence_below: float
    routing_precision_min: float
    routing_recall_min: float


@dataclass(frozen=True, slots=True)
class PrivateOCRResult:
    artifact_id: str
    sha256: str
    category: str
    gold_chars: int
    ocr_chars: int
    confidence: float | None
    cer: float
    wer: float
    latency_ms: float
    poor_quality: bool
    would_escalate: bool


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_private_ocr_suite(path: Path) -> PrivateOCRSuite:
    payload = json.loads(path.read_text(encoding="utf-8"))
    thresholds = payload["thresholds"]
    artifacts = tuple(
        PrivateOCRArtifact(
            artifact_id=str(item["id"]),
            sha256=str(item["sha256"]),
            category=str(item["category"]),
        )
        for item in payload["artifacts"]
    )
    if len({item.artifact_id for item in artifacts}) != len(artifacts):
        raise ValueError("artifact IDs must be unique")
    if len({item.sha256 for item in artifacts}) != len(artifacts):
        raise ValueError("artifact hashes must be unique")
    return PrivateOCRSuite(
        name=str(payload["name"]),
        page=int(payload.get("page", 1)),
        artifacts=artifacts,
        poor_cer_above=float(thresholds["poor_cer_above"]),
        poor_wer_above=float(thresholds["poor_wer_above"]),
        vlm_confidence_below=float(thresholds["vlm_confidence_below"]),
        routing_precision_min=float(thresholds["routing_precision_min"]),
        routing_recall_min=float(thresholds["routing_recall_min"]),
    )


def find_private_ocr_artifacts(
    suite: PrivateOCRSuite,
    roots: tuple[Path, ...],
) -> dict[str, Path]:
    wanted = {item.sha256: item.artifact_id for item in suite.artifacts}
    found: dict[str, Path] = {}
    for root in roots:
        for path in root.rglob("*.pdf"):
            digest = _file_sha256(path)
            artifact_id = wanted.get(digest)
            if artifact_id and artifact_id not in found:
                found[artifact_id] = path
                if len(found) == len(wanted):
                    return found
    return found


def evaluate_private_ocr_scale(
    suite: PrivateOCRSuite,
    *,
    roots: tuple[Path, ...],
    provider: OCRProvider,
) -> dict[str, Any]:
    matched = find_private_ocr_artifacts(suite, roots)
    missing = [
        item.artifact_id
        for item in suite.artifacts
        if item.artifact_id not in matched
    ]
    if missing:
        raise ValueError(f"private OCR artifacts not found by SHA-256: {missing}")

    results: list[PrivateOCRResult] = []
    for artifact in suite.artifacts:
        path = matched[artifact.artifact_id]
        content = path.read_bytes()
        reader = PdfReader(str(path))
        if len(reader.pages) < suite.page:
            raise ValueError(f"artifact {artifact.artifact_id} has no page {suite.page}")
        gold = _normalize_for_ocr(
            (reader.pages[suite.page - 1].extract_text() or "").strip()
        )
        if not gold:
            raise ValueError(
                f"artifact {artifact.artifact_id} has no native-text gold on page {suite.page}"
            )

        started = time.perf_counter()
        ocr = provider.extract_pdf(content, page_numbers=(suite.page,))
        latency_ms = (time.perf_counter() - started) * 1000.0
        actual = _normalize_for_ocr(ocr.text)
        cer = character_error_rate(gold, actual)
        wer = word_error_rate(gold, actual)
        confidence = ocr.mean_confidence
        poor_quality = cer > suite.poor_cer_above or wer > suite.poor_wer_above
        would_escalate = (
            confidence is None or confidence < suite.vlm_confidence_below
        )
        results.append(
            PrivateOCRResult(
                artifact_id=artifact.artifact_id,
                sha256=artifact.sha256,
                category=artifact.category,
                gold_chars=len(gold),
                ocr_chars=len(actual),
                confidence=confidence,
                cer=cer,
                wer=wer,
                latency_ms=latency_ms,
                poor_quality=poor_quality,
                would_escalate=would_escalate,
            )
        )

    poor = [item for item in results if item.poor_quality]
    escalated = [item for item in results if item.would_escalate]
    true_positive = sum(
        1 for item in results if item.poor_quality and item.would_escalate
    )
    true_negative = sum(
        1 for item in results if not item.poor_quality and not item.would_escalate
    )
    precision = true_positive / len(escalated) if escalated else 1.0
    recall = true_positive / len(poor) if poor else 1.0
    accuracy = (true_positive + true_negative) / len(results)
    latencies = sorted(item.latency_ms for item in results)
    p95_pos = (len(latencies) - 1) * 0.95
    lo = int(p95_pos)
    hi = min(lo + 1, len(latencies) - 1)
    frac = p95_pos - lo
    p95 = latencies[lo] * (1 - frac) + latencies[hi] * frac

    return {
        "benchmark": suite.name,
        "visibility": "private-derived",
        "cases": len(results),
        "categories": {
            category: sum(1 for item in results if item.category == category)
            for category in sorted({item.category for item in results})
        },
        "thresholds": {
            "poor_cer_above": suite.poor_cer_above,
            "poor_wer_above": suite.poor_wer_above,
            "vlm_confidence_below": suite.vlm_confidence_below,
        },
        "mean_cer": mean(item.cer for item in results),
        "median_cer": median(item.cer for item in results),
        "mean_wer": mean(item.wer for item in results),
        "median_wer": median(item.wer for item in results),
        "mean_confidence": mean(
            item.confidence for item in results if item.confidence is not None
        ),
        "latency_p50_ms": median(latencies),
        "latency_p95_ms": p95,
        "latency_max_ms": max(latencies),
        "poor_quality_cases": len(poor),
        "escalated_cases": len(escalated),
        "routing_precision": precision,
        "routing_recall": recall,
        "routing_accuracy": accuracy,
        "benchmark_passed": (
            precision >= suite.routing_precision_min
            and recall >= suite.routing_recall_min
        ),
        "results": [
            {
                "artifact_id": item.artifact_id,
                "sha256": item.sha256,
                "category": item.category,
                "page": suite.page,
                "gold_chars": item.gold_chars,
                "ocr_chars": item.ocr_chars,
                "confidence": item.confidence,
                "cer": item.cer,
                "wer": item.wer,
                "latency_ms": item.latency_ms,
                "poor_quality": item.poor_quality,
                "would_escalate": item.would_escalate,
            }
            for item in results
        ],
        "privacy_note": (
            "No source path, filename, native text or OCR text is emitted; "
            "only hashes, categories and metrics."
        ),
    }
