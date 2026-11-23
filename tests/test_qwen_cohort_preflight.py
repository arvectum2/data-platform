"""Offline-only Qwen cohort planning must not be mistaken for inference acceptance."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ingest_qwen_cohort_preflight.py"


def test_offline_qwen_preflight_has_exact_large_cohorts_and_no_model_calls() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--check-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=25,
        check=True,
    )
    data = json.loads(completed.stdout)
    assert data["mode"] == "OFFLINE_PREFLIGHT_ONLY"
    assert data["active_model_requests"] == 0
    assert data["production_mutations"] == 0
    assert data["requires_new_authorized_Qwen_window"] is True
    assert data["planned_concurrency_strata"] == [1, 2]
    assert data["required_observations_all_strata"] == 160
    assert [x["actual_chunks"] for x in data["cohorts"]] == [5, 10, 18, 27]
    assert all(1000 <= x["synthetic_bytes_per_document"] < 100000 for x in data["cohorts"])
    assert "synthetic://" not in completed.stdout


def test_offline_qwen_preflight_requires_flag() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode != 0
    assert "--check-only" in completed.stderr
