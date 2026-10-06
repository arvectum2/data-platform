from __future__ import annotations

import hashlib
import json
from pathlib import Path

from arvectum_data.evaluation.private_ocr_scale import (
    find_private_ocr_artifacts,
    load_private_ocr_suite,
)


def test_sha_only_suite_finds_private_artifacts_without_paths(tmp_path: Path) -> None:
    content = b"private-pdf-placeholder"
    digest = hashlib.sha256(content).hexdigest()
    pdf = tmp_path / "sensitive-name.pdf"
    pdf.write_bytes(content)
    suite_path = tmp_path / "suite.json"
    suite_path.write_text(
        json.dumps(
            {
                "name": "private",
                "page": 1,
                "thresholds": {
                    "poor_cer_above": 0.25,
                    "poor_wer_above": 0.5,
                    "vlm_confidence_below": 90,
                    "routing_precision_min": 1,
                    "routing_recall_min": 1
                },
                "artifacts": [
                    {"id": "a", "sha256": digest, "category": "procurement"}
                ]
            }
        )
    )

    suite = load_private_ocr_suite(suite_path)
    matched = find_private_ocr_artifacts(suite, (tmp_path,))

    assert matched == {"a": pdf}
    assert "sensitive-name" not in json.dumps(
        {
            "id": suite.artifacts[0].artifact_id,
            "sha256": suite.artifacts[0].sha256,
            "category": suite.artifacts[0].category,
        }
    )


def test_repository_private_ocr_suite_is_frozen() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "benchmarks"
        / "private_runtime_ocr_scale_v1.json"
    )
    suite = load_private_ocr_suite(path)

    assert suite.name == "private-runtime-ocr-scale-v1"
    assert len(suite.artifacts) == 9
    assert sum(item.category == "procurement" for item in suite.artifacts) == 8
    assert sum(item.category == "business" for item in suite.artifacts) == 1
