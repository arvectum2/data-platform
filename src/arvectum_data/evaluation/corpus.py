from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median
from typing import Any, Literal, Mapping, Sequence

from ..documents.ingest import ingest_file
from ..documents.ocr import OCRProvider
from .metrics import character_error_rate, word_error_rate


CorpusVisibility = Literal["public", "private-derived"]
_PAGE_MARKER = re.compile(r"\[Page\s+\d+\]\s*", flags=re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class CorpusArtifact:
    artifact_id: str
    file: str
    sha256: str
    format: str
    source_kind: str
    language: str
    visibility: CorpusVisibility
    source_ref: str = ""
    required_text: tuple[str, ...] = ()
    min_text_chars: int = 1
    expected_status: str = "extracted"
    ocr_required: bool = False
    gold_text_file: str | None = None
    gold_sha256: str | None = None
    max_cer: float | None = None
    max_wer: float | None = None
    required_rows: tuple[tuple[str, ...], ...] = ()
    required_fields: tuple[tuple[str, str], ...] = ()
    min_structure_score: float | None = None
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.artifact_id.strip():
            raise ValueError("artifact_id must not be blank")
        if not self.file.strip():
            raise ValueError("file must not be blank")
        if len(self.sha256) != 64 or any(ch not in "0123456789abcdef" for ch in self.sha256):
            raise ValueError("sha256 must be a lowercase hexadecimal digest")
        if not self.format.strip():
            raise ValueError("format must not be blank")
        if not self.source_kind.strip():
            raise ValueError("source_kind must not be blank")
        if not self.language.strip():
            raise ValueError("language must not be blank")
        if self.visibility not in {"public", "private-derived"}:
            raise ValueError(f"unsupported visibility: {self.visibility}")
        if self.min_text_chars < 0:
            raise ValueError("min_text_chars must be non-negative")
        if self.ocr_required and not self.gold_text_file:
            raise ValueError("ocr_required artifacts must define gold_text_file")
        if self.gold_text_file and not self.gold_sha256:
            raise ValueError("gold_text_file requires gold_sha256")
        if self.gold_sha256 and (
            len(self.gold_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in self.gold_sha256)
        ):
            raise ValueError("gold_sha256 must be a lowercase hexadecimal digest")
        if self.max_cer is not None and self.max_cer < 0:
            raise ValueError("max_cer must be non-negative")
        if self.max_wer is not None and self.max_wer < 0:
            raise ValueError("max_wer must be non-negative")
        if self.min_structure_score is not None and not 0 <= self.min_structure_score <= 1:
            raise ValueError("min_structure_score must be between 0 and 1")
        if any(not row for row in self.required_rows):
            raise ValueError("required_rows must not contain empty rows")
        if any(not label.strip() or not value.strip() for label, value in self.required_fields):
            raise ValueError("required_fields labels and values must not be blank")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CorpusArtifact":
        return cls(
            artifact_id=str(payload["id"]),
            file=str(payload["file"]),
            sha256=str(payload["sha256"]),
            format=str(payload["format"]),
            source_kind=str(payload["source_kind"]),
            language=str(payload["language"]),
            visibility=str(payload["visibility"]),  # type: ignore[arg-type]
            source_ref=str(payload.get("source_ref") or ""),
            required_text=tuple(str(item) for item in payload.get("required_text") or ()),
            min_text_chars=int(payload.get("min_text_chars", 1)),
            expected_status=str(payload.get("expected_status", "extracted")),
            ocr_required=bool(payload.get("ocr_required", False)),
            gold_text_file=(
                str(payload["gold_text_file"]) if payload.get("gold_text_file") else None
            ),
            gold_sha256=str(payload["gold_sha256"]) if payload.get("gold_sha256") else None,
            max_cer=float(payload["max_cer"]) if payload.get("max_cer") is not None else None,
            max_wer=float(payload["max_wer"]) if payload.get("max_wer") is not None else None,
            required_rows=tuple(
                tuple(str(cell) for cell in row)
                for row in payload.get("required_rows") or ()
            ),
            required_fields=tuple(
                (str(item["label"]), str(item["value"]))
                for item in payload.get("required_fields") or ()
            ),
            min_structure_score=(
                float(payload["min_structure_score"])
                if payload.get("min_structure_score") is not None
                else None
            ),
            tags=tuple(str(item) for item in payload.get("tags") or ()),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class CorpusManifest:
    name: str
    version: int
    artifacts: tuple[CorpusArtifact, ...]
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("corpus name must not be blank")
        if self.version < 1:
            raise ValueError("corpus version must be positive")
        if not self.artifacts:
            raise ValueError("corpus must contain at least one artifact")
        ids = [artifact.artifact_id for artifact in self.artifacts]
        if len(ids) != len(set(ids)):
            raise ValueError("corpus artifact IDs must be unique")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CorpusManifest":
        raw_artifacts = payload.get("artifacts")
        if not isinstance(raw_artifacts, Sequence) or isinstance(
            raw_artifacts, (str, bytes)
        ):
            raise ValueError("artifacts must be a list")
        return cls(
            name=str(payload["name"]),
            version=int(payload["version"]),
            description=str(payload.get("description") or ""),
            metadata=dict(payload.get("metadata") or {}),
            artifacts=tuple(CorpusArtifact.from_dict(item) for item in raw_artifacts),
        )


@dataclass(frozen=True, slots=True)
class CorpusArtifactEvaluation:
    artifact_id: str
    format: str
    status: str
    text_chars: int
    passed: bool
    benchmark_passed: bool
    skipped: bool
    latency_ms: float
    missing_required_text: tuple[str, ...] = ()
    cer: float | None = None
    wer: float | None = None
    ocr_confidence: float | None = None
    max_cer: float | None = None
    max_wer: float | None = None
    structure_score: float | None = None
    min_structure_score: float | None = None
    matched_structure_checks: int = 0
    total_structure_checks: int = 0
    skip_reason: str = ""


@dataclass(frozen=True, slots=True)
class CorpusEvaluationSummary:
    corpus_name: str
    total_artifacts: int
    executed_artifacts: int
    skipped_artifacts: int
    ingestion_success_rate: float
    benchmark_success_rate: float
    success_by_format: Mapping[str, float]
    mean_cer: float | None
    mean_wer: float | None
    mean_structure_score: float | None
    latency_p50_ms: float
    latency_p95_ms: float
    latency_max_ms: float
    results: tuple[CorpusArtifactEvaluation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_name": self.corpus_name,
            "total_artifacts": self.total_artifacts,
            "executed_artifacts": self.executed_artifacts,
            "skipped_artifacts": self.skipped_artifacts,
            "ingestion_success_rate": self.ingestion_success_rate,
            "benchmark_success_rate": self.benchmark_success_rate,
            "success_by_format": dict(self.success_by_format),
            "mean_cer": self.mean_cer,
            "mean_wer": self.mean_wer,
            "mean_structure_score": self.mean_structure_score,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "latency_max_ms": self.latency_max_ms,
            "results": [
                {
                    "artifact_id": item.artifact_id,
                    "format": item.format,
                    "status": item.status,
                    "text_chars": item.text_chars,
                    "passed": item.passed,
                    "benchmark_passed": item.benchmark_passed,
                    "skipped": item.skipped,
                    "latency_ms": item.latency_ms,
                    "missing_required_text": list(item.missing_required_text),
                    "cer": item.cer,
                    "wer": item.wer,
                    "ocr_confidence": item.ocr_confidence,
                    "max_cer": item.max_cer,
                    "max_wer": item.max_wer,
                    "structure_score": item.structure_score,
                    "min_structure_score": item.min_structure_score,
                    "matched_structure_checks": item.matched_structure_checks,
                    "total_structure_checks": item.total_structure_checks,
                    "skip_reason": item.skip_reason,
                }
                for item in self.results
            ],
        }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve_under(base_dir: Path, relative_path: str) -> Path:
    resolved_base = base_dir.resolve()
    resolved = (base_dir / relative_path).resolve()
    if not resolved.is_relative_to(resolved_base):
        raise ValueError(f"corpus path escapes manifest directory: {relative_path}")
    return resolved


def load_corpus_manifest(path: Path) -> CorpusManifest:
    return CorpusManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def validate_corpus_manifest(path: Path) -> CorpusManifest:
    manifest = load_corpus_manifest(path)
    base_dir = path.parent
    for artifact in manifest.artifacts:
        artifact_path = _resolve_under(base_dir, artifact.file)
        if not artifact_path.is_file():
            raise ValueError(f"corpus artifact does not exist: {artifact.file}")
        actual_hash = file_sha256(artifact_path)
        if actual_hash != artifact.sha256:
            raise ValueError(
                f"corpus digest mismatch for {artifact.artifact_id}: "
                f"expected {artifact.sha256}, got {actual_hash}"
            )
        if artifact.gold_text_file:
            gold_path = _resolve_under(base_dir, artifact.gold_text_file)
            if not gold_path.is_file():
                raise ValueError(
                    f"corpus gold text does not exist for {artifact.artifact_id}: "
                    f"{artifact.gold_text_file}"
                )
            gold_hash = file_sha256(gold_path)
            if gold_hash != artifact.gold_sha256:
                raise ValueError(
                    f"gold digest mismatch for {artifact.artifact_id}: "
                    f"expected {artifact.gold_sha256}, got {gold_hash}"
                )
    return manifest


def _normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    return " ".join(text.split())


def _normalize_for_ocr(text: str) -> str:
    return _normalize_text(_PAGE_MARKER.sub(" ", text))


def _normalized_lines(text: str) -> tuple[str, ...]:
    return tuple(
        _normalize_text(line)
        for line in text.splitlines()
        if _normalize_text(line)
    )


def _row_cells(line: str) -> tuple[str, ...]:
    return tuple(_normalize_text(cell) for cell in line.split("\t") if _normalize_text(cell))


def _contains_ordered_cells(actual: tuple[str, ...], expected: tuple[str, ...]) -> bool:
    position = 0
    for expected_cell in expected:
        normalized_expected = _normalize_text(expected_cell)
        while position < len(actual):
            if normalized_expected in actual[position]:
                position += 1
                break
            position += 1
        else:
            return False
    return True


def _structure_score(
    text: str,
    *,
    required_rows: tuple[tuple[str, ...], ...],
    required_fields: tuple[tuple[str, str], ...],
) -> tuple[float | None, int, int]:
    checks: list[bool] = []
    tabular_rows = tuple(_row_cells(line) for line in text.splitlines() if "\t" in line)

    for expected_row in required_rows:
        checks.append(
            any(
                _contains_ordered_cells(actual_row, expected_row)
                for actual_row in tabular_rows
            )
        )

    normalized_text = _normalize_text(text)
    for label, value in required_fields:
        normalized_label = _normalize_text(label)
        normalized_value = _normalize_text(value)
        label_index = normalized_text.find(normalized_label)
        value_index = normalized_text.find(normalized_value, max(0, label_index))
        checks.append(label_index >= 0 and value_index >= label_index)

    if not checks:
        return None, 0, 0
    matched = sum(1 for item in checks if item)
    return matched / len(checks), matched, len(checks)


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


def evaluate_corpus(
    manifest_path: Path,
    *,
    include_ocr: bool = False,
    ocr_provider: OCRProvider | None = None,
) -> CorpusEvaluationSummary:
    manifest = validate_corpus_manifest(manifest_path)
    base_dir = manifest_path.parent
    results: list[CorpusArtifactEvaluation] = []

    for artifact in manifest.artifacts:
        if artifact.ocr_required and not include_ocr:
            results.append(
                CorpusArtifactEvaluation(
                    artifact_id=artifact.artifact_id,
                    format=artifact.format,
                    status="skipped",
                    text_chars=0,
                    passed=False,
                    benchmark_passed=False,
                    skipped=True,
                    latency_ms=0.0,
                    skip_reason="ocr-disabled",
                )
            )
            continue
        if artifact.ocr_required and ocr_provider is None:
            raise ValueError("include_ocr=True requires an OCR provider")

        artifact_path = _resolve_under(base_dir, artifact.file)
        started = time.perf_counter()
        ingested = ingest_file(
            artifact_path,
            collection_id=f"benchmark:{manifest.name}",
            source_type="benchmark",
            canonical_uri=f"benchmark://{manifest.name}/{artifact.artifact_id}",
            ocr_provider=ocr_provider if artifact.ocr_required else None,
        )
        latency_ms = (time.perf_counter() - started) * 1000.0

        text = ingested.document.text
        normalized_text = _normalize_text(text)
        missing = tuple(
            fragment
            for fragment in artifact.required_text
            if _normalize_text(fragment) not in normalized_text
        )
        passed = (
            ingested.document.extraction_status == artifact.expected_status
            and len(text.strip()) >= artifact.min_text_chars
            and not missing
        )

        cer: float | None = None
        wer: float | None = None
        ocr_confidence: float | None = None
        if artifact.gold_text_file:
            gold = _resolve_under(base_dir, artifact.gold_text_file).read_text(encoding="utf-8")
            reference = _normalize_for_ocr(gold)
            hypothesis = _normalize_for_ocr(text)
            cer = character_error_rate(reference, hypothesis)
            wer = word_error_rate(reference, hypothesis)
            ocr_meta = ingested.document.metadata.get("ocr", {})
            if isinstance(ocr_meta, Mapping):
                raw_confidence = ocr_meta.get("mean_confidence")
                if raw_confidence is not None:
                    ocr_confidence = float(raw_confidence)

        structure_score, matched_structure, total_structure = _structure_score(
            text,
            required_rows=artifact.required_rows,
            required_fields=artifact.required_fields,
        )

        ocr_thresholds_passed = True
        if artifact.max_cer is not None:
            ocr_thresholds_passed = cer is not None and cer <= artifact.max_cer
        if artifact.max_wer is not None:
            ocr_thresholds_passed = (
                ocr_thresholds_passed
                and wer is not None
                and wer <= artifact.max_wer
            )
        structure_threshold_passed = True
        if artifact.min_structure_score is not None:
            structure_threshold_passed = (
                structure_score is not None
                and structure_score >= artifact.min_structure_score
            )
        benchmark_passed = passed and ocr_thresholds_passed and structure_threshold_passed

        results.append(
            CorpusArtifactEvaluation(
                artifact_id=artifact.artifact_id,
                format=artifact.format,
                status=ingested.document.extraction_status,
                text_chars=len(text),
                passed=passed,
                benchmark_passed=benchmark_passed,
                skipped=False,
                latency_ms=latency_ms,
                missing_required_text=missing,
                cer=cer,
                wer=wer,
                ocr_confidence=ocr_confidence,
                max_cer=artifact.max_cer,
                max_wer=artifact.max_wer,
                structure_score=structure_score,
                min_structure_score=artifact.min_structure_score,
                matched_structure_checks=matched_structure,
                total_structure_checks=total_structure,
            )
        )

    executed = [item for item in results if not item.skipped]
    successes = [item for item in executed if item.passed]
    benchmark_successes = [item for item in executed if item.benchmark_passed]
    formats = sorted({item.format for item in executed})
    success_by_format = {
        fmt: mean(
            1.0 if item.passed else 0.0
            for item in executed
            if item.format == fmt
        )
        for fmt in formats
    }
    cer_values = [item.cer for item in executed if item.cer is not None]
    wer_values = [item.wer for item in executed if item.wer is not None]
    structure_values = [
        item.structure_score
        for item in executed
        if item.structure_score is not None
    ]
    latencies = [item.latency_ms for item in executed]

    return CorpusEvaluationSummary(
        corpus_name=manifest.name,
        total_artifacts=len(results),
        executed_artifacts=len(executed),
        skipped_artifacts=len(results) - len(executed),
        ingestion_success_rate=(len(successes) / len(executed)) if executed else 0.0,
        benchmark_success_rate=(
            len(benchmark_successes) / len(executed)
            if executed
            else 0.0
        ),
        success_by_format=success_by_format,
        mean_cer=mean(cer_values) if cer_values else None,
        mean_wer=mean(wer_values) if wer_values else None,
        mean_structure_score=mean(structure_values) if structure_values else None,
        latency_p50_ms=median(latencies) if latencies else 0.0,
        latency_p95_ms=_percentile(latencies, 0.95),
        latency_max_ms=max(latencies, default=0.0),
        results=tuple(results),
    )
