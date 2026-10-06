from __future__ import annotations

import json
from pathlib import Path

import pytest

from arvectum_data.evaluation.catalog import (
    BenchmarkCatalog,
    file_sha256,
    validate_benchmark_catalog,
)
from arvectum_data.evaluation.metrics import (
    character_error_rate,
    ndcg_at_k,
    set_precision_recall,
    word_error_rate,
)


def test_ocr_error_metrics_are_deterministic() -> None:
    assert character_error_rate("кот", "кит") == pytest.approx(1 / 3)
    assert word_error_rate("оплата в 10 дней", "оплата за 10 дней") == pytest.approx(0.25)
    assert character_error_rate("", "") == 0.0
    assert word_error_rate("", "лишнее") == 1.0


def test_ndcg_rewards_correct_graded_order() -> None:
    relevance = {"best": 3.0, "good": 2.0, "ok": 1.0}

    assert ndcg_at_k(relevance, ["best", "good", "ok"], k=3) == pytest.approx(1.0)
    assert ndcg_at_k(relevance, ["ok", "good", "best"], k=3) < 1.0
    assert ndcg_at_k(relevance, ["miss"], k=3) == 0.0


def test_ndcg_does_not_double_count_duplicate_result_identity() -> None:
    relevance = {"expected": 1.0}

    score = ndcg_at_k(
        relevance,
        ["expected", "expected", "expected", "miss"],
        k=5,
    )

    assert score == pytest.approx(1.0)


def test_set_precision_recall_supports_citation_style_metrics() -> None:
    precision, recall = set_precision_recall(
        ["source-a", "source-b"],
        ["source-a", "source-c"],
    )
    assert precision == pytest.approx(0.5)
    assert recall == pytest.approx(0.5)


def test_repository_benchmark_catalog_is_frozen_and_valid() -> None:
    root = Path(__file__).resolve().parents[2]
    catalog = validate_benchmark_catalog(root / "benchmarks" / "catalog_v1.json")

    assert catalog.version == 1
    assert {item.visibility for item in catalog.suites} == {
        "public",
        "private-derived",
    }
    assert all(item.thresholds for item in catalog.suites)


    sync = next(item for item in catalog.suites if item.suite_id == "sync-efficiency-v1")
    assert sync.items_key == "scenarios"


def test_catalog_rejects_tampered_suite(tmp_path: Path) -> None:
    suite = tmp_path / "suite.json"
    suite.write_text(
        json.dumps({"name": "sample", "cases": [{"id": "one"}]}),
        encoding="utf-8",
    )
    catalog = {
        "version": 1,
        "suites": [
            {
                "id": "sample",
                "file": "suite.json",
                "sha256": file_sha256(suite),
                "case_count": 1,
                "visibility": "public",
                "dimensions": ["retrieval"],
                "thresholds": {"mrr": 1.0},
            }
        ],
    }
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    validate_benchmark_catalog(catalog_path)
    suite.write_text(json.dumps({"name": "changed", "cases": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="digest mismatch"):
        validate_benchmark_catalog(catalog_path)


def test_catalog_rejects_invalid_digest() -> None:
    with pytest.raises(ValueError, match="sha256"):
        BenchmarkCatalog.from_dict(
            {
                "version": 1,
                "suites": [
                    {
                        "id": "bad",
                        "file": "../secret.json",
                        "sha256": "not-a-digest",
                        "case_count": 1,
                        "visibility": "private-derived",
                        "dimensions": ["isolation"],
                    }
                ],
            }
        )
