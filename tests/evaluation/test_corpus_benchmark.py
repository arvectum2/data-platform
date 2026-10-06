from __future__ import annotations

from pathlib import Path

import pytest

from arvectum_data.documents.ocr import OCRDocumentResult, OCRPageResult
from arvectum_data.evaluation.corpus import (
    evaluate_corpus,
    validate_corpus_manifest,
)


def _manifest() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "benchmarks"
        / "corpora"
        / "public_v1"
        / "manifest.json"
    )


def test_repository_public_corpus_is_frozen_and_valid() -> None:
    manifest = validate_corpus_manifest(_manifest())

    assert manifest.version == 1
    assert len(manifest.artifacts) == 7
    assert {item.format for item in manifest.artifacts} == {
        "pdf",
        "scanned-pdf",
        "docx",
        "xlsx",
        "html",
    }
    assert all(item.visibility == "public" for item in manifest.artifacts)


def test_public_corpus_extracts_all_non_ocr_formats() -> None:
    summary = evaluate_corpus(_manifest())

    assert summary.total_artifacts == 7
    assert summary.executed_artifacts == 5
    assert summary.skipped_artifacts == 2
    assert summary.ingestion_success_rate == pytest.approx(1.0)
    assert summary.benchmark_success_rate == pytest.approx(1.0)
    assert summary.success_by_format == {
        "docx": 1.0,
        "html": 1.0,
        "pdf": 1.0,
        "xlsx": 1.0,
    }
    assert all(item.passed for item in summary.results if not item.skipped)


def test_ocr_gold_metrics_are_executable_with_provider() -> None:
    manifest = validate_corpus_manifest(_manifest())
    base = _manifest().parent
    gold_by_hash = {
        item.sha256: (base / item.gold_text_file).read_text(encoding="utf-8").strip()
        for item in manifest.artifacts
        if item.ocr_required and item.gold_text_file
    }

    class ExactGoldOCR:
        provider_name = "fake-gold"

        def extract_pdf(
            self,
            content: bytes,
            *,
            page_numbers: tuple[int, ...],
        ) -> OCRDocumentResult:
            import hashlib

            assert content.startswith(b"%PDF-")
            gold = gold_by_hash[hashlib.sha256(content).hexdigest()]
            return OCRDocumentResult(
                tuple(
                    OCRPageResult(
                        page_number=page_number,
                        text=gold,
                        confidence=100.0,
                        provider=self.provider_name,
                    )
                    for page_number in page_numbers
                ),
                self.provider_name,
            )

    summary = evaluate_corpus(
        _manifest(),
        include_ocr=True,
        ocr_provider=ExactGoldOCR(),
    )

    assert summary.executed_artifacts == 7
    assert summary.skipped_artifacts == 0
    assert summary.ingestion_success_rate == pytest.approx(1.0)
    assert summary.benchmark_success_rate == pytest.approx(1.0)
    assert summary.mean_cer == pytest.approx(0.0)
    assert summary.mean_wer == pytest.approx(0.0)
    scan_result = next(item for item in summary.results if item.format == "scanned-pdf")
    assert scan_result.ocr_confidence == pytest.approx(100.0)
