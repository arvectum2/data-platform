from __future__ import annotations

from pathlib import Path

from arvectum_data.evaluation.faithfulness import load_faithfulness_suite


def _suite():
    return load_faithfulness_suite(
        Path(__file__).resolve().parents[2]
        / "benchmarks"
        / "faithfulness_real_v1.json"
    )


def test_real_source_faithfulness_suite_is_frozen_and_non_synthetic() -> None:
    suite = _suite()

    assert suite.name == "faithfulness-real-v1"
    assert len(suite.cases) == 5
    assert suite.metadata["synthetic"] is False
    assert suite.metadata["sut_output_used_for_truth"] is False
    assert suite.metadata["corpus_manifest"] == "corpora/public_v1/manifest.json"


def test_real_source_faithfulness_cases_keep_source_artifact_identity() -> None:
    suite = _suite()

    assert all(case.metadata.get("source_artifact_ids") for case in suite.cases)
    assert {
        artifact_id
        for case in suite.cases
        for artifact_id in case.metadata["source_artifact_ids"]
    } == {
        "procurement-control-notice-pdf",
        "procurement-nmck-docx",
        "arvectum-photo-size-html",
    }
