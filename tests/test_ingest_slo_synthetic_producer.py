from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ingest_slo_synthetic_producer import (  # noqa: E402
    MAX_SAMPLES,
    SAMPLES_PER_COHORT,
    SUPPORTED_CONCURRENCY,
    SUPPORTED_SIZES,
    synthetic_payload,
    run_bounded_experiment,
)


def test_producer_is_statistically_bounded() -> None:
    assert len(SUPPORTED_SIZES) * len(SUPPORTED_CONCURRENCY) * SAMPLES_PER_COHORT == 80
    assert MAX_SAMPLES >= 80
    assert SUPPORTED_CONCURRENCY == (1, 4)


@pytest.mark.parametrize("size", [8192, 65536])
def test_synthetic_payload_has_exact_approved_size_and_not_private(size: int) -> None:
    item = synthetic_payload(size, 7)
    assert len(item) == size
    assert b"synthetic staging token" in item
    assert b"http" not in item


def test_disallowed_size_fails_closed() -> None:
    with pytest.raises(ValueError):
        synthetic_payload(512000, 1)
    with pytest.raises(ValueError):
        synthetic_payload(8192, -1)


@pytest.mark.parametrize("path", [Path("/tmp/../../etc/passwd.jsonl"), Path("/var/tmp/unsafe.jsonl")])
def test_output_cannot_target_other_directory(monkeypatch, path: Path) -> None:
    def no_connect() -> None:
        raise AssertionError("must not attempt connection for invalid output")
    monkeypatch.setattr("ingest_slo_synthetic_producer._prepare_clean_disposable_storage", no_connect)
    with pytest.raises(ValueError, match="inside /tmp"):
        run_bounded_experiment(path)
