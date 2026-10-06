from __future__ import annotations

from pathlib import Path

import pytest

from arvectum_data.evaluation.corpus import (
    evaluate_corpus,
    validate_corpus_manifest,
)


def _manifest() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "benchmarks"
        / "corpora"
        / "private_v1"
        / "manifest.json"
    )


def test_private_derived_corpus_is_frozen_and_valid() -> None:
    manifest = validate_corpus_manifest(_manifest())

    assert manifest.version == 1
    assert len(manifest.artifacts) == 4
    assert all(item.visibility == "private-derived" for item in manifest.artifacts)
    assert {item.source_kind for item in manifest.artifacts} == {
        "procurement",
        "product-research",
        "business",
    }


def test_private_derived_corpus_covers_legacy_mixed_and_malformed() -> None:
    summary = evaluate_corpus(_manifest())

    assert summary.total_artifacts == 4
    assert summary.executed_artifacts == 4
    assert summary.skipped_artifacts == 0
    assert summary.ingestion_success_rate == pytest.approx(1.0)
    assert summary.benchmark_success_rate == pytest.approx(1.0)

    by_id = {item.artifact_id: item for item in summary.results}
    legacy = by_id["legacy-procurement-xls"]
    assert legacy.status == "extracted"
    assert legacy.structure_score == pytest.approx(1.0)
    assert legacy.text_chars >= 6000

    assert by_id["product-research-competitive-mixed"].status == "extracted"
    assert by_id["business-market-validation-en"].status == "extracted"

    malformed = by_id["malformed-procurement-docx"]
    assert malformed.status == "empty"
    assert malformed.text_chars == 0
    assert malformed.benchmark_passed is True
