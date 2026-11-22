from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ingest_slo_qwen_stage_gate import (  # noqa: E402
    EXPECTED_MODEL_BYTES,
    ISOLATED_PROFILE,
    evaluate,
)

NOW = datetime(2026, 11, 22, 16, 30, tzinfo=UTC)


def safe_state() -> dict:
    return {
        "status": "pass",
        "mode": "normal",
        "checked_at_utc": NOW.isoformat(),
        "sample": {
            "memory_free": 62,
            "pressure": 0,
            "cpu_busy": 20,
            "gpu_busy": 10,
            "thermal": 0,
            "disk_free_gib": 90,
        },
    }


def check(state=None, **changes):
    defaults = {
        "swap_used_mib": 512,
        "stage_port_free": True,
        "model_size": EXPECTED_MODEL_BYTES,
        "binary_available": True,
        "mac_arm64": True,
        "now": NOW,
    }
    defaults.update(changes)
    return evaluate(safe_state() if state is None else state, **defaults)


def test_exact_safe_inputs_allow_only_a_nonexecuting_plan():
    result = check()
    assert result["admission"] == "pass"
    assert result["reason_codes"] == []
    assert not result["model_launch_executed"]
    assert not result["live_embedding_server_touched"]
    assert not result["production_readiness_proven"]
    assert ISOLATED_PROFILE["port"] != result["live_embedding_server_port"]
    assert ISOLATED_PROFILE["gpu_layers"] == 0
    assert ISOLATED_PROFILE["parallel"] == 1
    assert ISOLATED_PROFILE["max_runtime_seconds"] <= 420


@pytest.mark.parametrize(("mutation", "reason"), [
    ({"mode": "reduced"}, "governor_not_normal"),
    ({"status": "error"}, "governor_unhealthy"),
    ({"checked_at_utc": "2026-11-22T16:00:00Z"}, "governor_stale"),
    ({"checked_at_utc": "invalid"}, "governor_stale"),
    ({"checked_at_utc": (NOW + timedelta(seconds=30)).isoformat()}, "governor_stale"),
])
def test_governor_status_or_freshness_blocks(mutation, reason):
    result = check(state={**safe_state(), **mutation})
    assert result["admission"] == "blocked"
    assert reason in result["reason_codes"]


@pytest.mark.parametrize(("sample_patch", "reason"), [
    ({"memory_free": 34}, "memory_headroom_low"),
    ({"memory_free": True}, "memory_headroom_low"),
    ({"pressure": 2}, "memory_pressure_high_or_unknown"),
    ({"cpu_busy": 99}, "cpu_busy_or_unknown"),
    ({"gpu_busy": 99}, "gpu_busy_or_unknown"),
    ({"thermal": 1}, "thermal_warning_or_unknown"),
    ({"disk_free_gib": 9}, "disk_headroom_low"),
])
def test_unsafe_telemetry_blocks(sample_patch, reason):
    state = safe_state()
    state["sample"] = {**state["sample"], **sample_patch}
    result = check(state=state)
    assert result["admission"] == "blocked"
    assert reason in result["reason_codes"]


@pytest.mark.parametrize(("override", "reason"), [
    ({"swap_used_mib": 6200}, "swap_used_too_high_or_unknown"),
    ({"swap_used_mib": None}, "swap_used_too_high_or_unknown"),
    ({"stage_port_free": False}, "stage_port_in_use"),
    ({"model_size": 4279660225}, "model_identity_size_mismatch"),
    ({"binary_available": False}, "staging_binary_unavailable"),
    ({"mac_arm64": False}, "unexpected_host"),
])
def test_external_preconditions_block(override, reason):
    result = check(**override)
    assert result["admission"] == "blocked"
    assert reason in result["reason_codes"]


def test_missing_governor_and_missing_sample_fail_closed():
    result = check(state={})
    assert result["admission"] == "blocked"
    assert "governor_stale" in result["reason_codes"]
    assert "memory_headroom_low" in result["reason_codes"]


def test_realistic_reduced_state_is_blocked_with_no_model_start():
    state = safe_state()
    state["mode"] = "reduced"
    state["sample"].update(memory_free=34, pressure=2)
    result = check(state=state, swap_used_mib=6295)
    assert result["admission"] == "blocked"
    assert not result["model_launch_executed"]
    assert not result["live_embedding_server_touched"]
    assert {"governor_not_normal", "memory_headroom_low",
            "memory_pressure_high_or_unknown", "swap_used_too_high_or_unknown"} <= set(
        result["reason_codes"]
    )
