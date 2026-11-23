from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ingest_slo_staging_analysis import analyze  # noqa: E402


def _sample(*, ms: int = 8_000, size: int = 1_000, concurrency: int = 1, status: int = 200) -> dict:
    return {
        "synthetic": True,
        "bytes": size,
        "chunks": 3,
        "concurrency": concurrency,
        "retry_count": 0,
        "status_code": status,
        "total_ms": ms,
        "decode_ms": 100,
        "chunk_ms": 100,
        "embed_ms": 500,
        "db_ms": 50,
    }


def _make(tmp_path: Path, items: list[dict]) -> Path:
    path = tmp_path / "synthetic.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in items), encoding="utf-8")
    return path


def test_sufficient_fast_synthetic_rows_do_not_claim_production(tmp_path):
    result = analyze(_make(tmp_path, [_sample()] * 20))
    assert result["overall"]["status"] == "green"
    assert result["production_slo_proven"] is False
    assert result["overall"]["observations"] == 20
    assert result["overall"]["p95_ms"] == 8_000
    assert "synthetic.jsonl" not in str(result)


def test_red_latency_and_error_both_detected(tmp_path):
    result = analyze(_make(tmp_path, [_sample(ms=18_887)] * 19 + [_sample(ms=18_887, status=500)]))
    assert result["overall"]["status"] == "red"
    assert result["overall"]["error_rate"] == 0.05
    assert result["overall"]["p95_ms"] == 18_887


def test_insufficient_cohort_does_not_claim_green(tmp_path):
    result = analyze(_make(tmp_path, [_sample(size=5)] * 19 + [_sample(size=500_000)]))
    assert result["overall"]["status"] == "green"
    assert all(group["status"] == "insufficient-data" for group in result["by_input_size"].values())


@pytest.mark.parametrize("patch", [
    {"document_text": "PRIVATE DOCUMENT"},
    {"source_id": "PRIVATE_SOURCE"},
    {"synthetic": False},
    {"bytes": True},
    {"total_ms": 10},
    {"concurrency": 0},
    {"status_code": 601},
    {"embed_ms": -1},
])
def test_fail_closed_on_unexpected_or_inconsistent_fields(tmp_path, patch):
    item = {**_sample(), **patch}
    path = _make(tmp_path, [item])
    with pytest.raises(ValueError, match="invalid synthetic observation") as error:
        analyze(path)
    assert "PRIVATE" not in str(error.value)


def test_fail_closed_for_empty_and_oversized_input(tmp_path):
    with pytest.raises(ValueError, match="no synthetic"):
        analyze(_make(tmp_path, []))
    p = tmp_path / "oversized.jsonl"
    p.write_text("x" * 5_000_001)
    with pytest.raises(ValueError, match="oversized"):
        analyze(p)


def test_disjoint_categorical_grouping(tmp_path):
    result = analyze(_make(tmp_path, [_sample(size=65536, concurrency=1)] * 20 + [_sample(size=65537, concurrency=5)] * 20))
    assert sorted(result["by_input_size"]) == ["up_to_256KiB", "up_to_64KiB"]
    assert sorted(result["by_concurrency"]) == ["five_plus", "one"]
    assert all(bucket["observations"] == 20 for bucket in result["by_concurrency"].values())

def test_exact_synthetic_sizes_and_joint_cells_have_independent_sample_gates(tmp_path):
    rows = [
        _sample(size=size, concurrency=concurrency)
        for size in (8192, 65536)
        for concurrency in (1, 4)
        for _ in range(20)
    ]
    result = analyze(_make(tmp_path, rows))
    assert {name: data["observations"] for name, data in result["by_input_size"].items()} == {
        "up_to_8KiB": 40,
        "up_to_64KiB": 40,
    }
    assert sorted(result["by_size_and_concurrency"]) == [
        "up_to_64KiB__one",
        "up_to_64KiB__two_to_four",
        "up_to_8KiB__one",
        "up_to_8KiB__two_to_four",
    ]
    assert all(
        group["observations"] == 20 and group["status"] == "green"
        for group in result["by_size_and_concurrency"].values()
    )
    assert result["production_slo_proven"] is False
