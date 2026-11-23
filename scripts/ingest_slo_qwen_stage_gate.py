"""Fail-closed Mac mini resource admission for a SEPARATE Qwen3-4B synthetic stage.

This module NEVER launches an embedding model and NEVER contacts the live server.
A future isolated runner must invoke this check immediately before launch and
enforce an independent runtime memory/thermal kill switch and cleanup.
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

GOVERNOR = Path("/Users/master/ArvectumSafe/runtime/ta-resource-governor/health.json")
MODEL = Path(
    "/Volumes/ArvectumSSD/Models/embeddings/embeddings/"
    "Qwen3-Embedding-4B-GGUF/Qwen3-Embedding-4B-Q8_0.gguf"
)
BINARY = Path("/opt/homebrew/bin/llama-server")
EXPECTED_MODEL_BYTES = 4_279_660_224
STAGE_PORT = 18190
LIVE_PORT = 8090
MAX_STATE_AGE_SECONDS = 300
MIN_FREE_MEMORY_PERCENT = 50
MAX_SWAP_USED_MIB = 2_048
MIN_DISK_FREE_GIB = 20

# This launch profile is an audited SUGGESTION, not an executed command.
# CPU-only to avoid competing with the live GPU model. No public exposure.
ISOLATED_PROFILE = {
    "host": "127.0.0.1",
    "port": STAGE_PORT,
    "gpu_layers": 0,
    "threads": 2,
    "threads_batch": 2,
    "parallel": 1,
    "context_tokens": 4096,
    "embeddings_only": True,
    "webui": False,
    "max_runtime_seconds": 420,
    "synthetic_input_only": True,
}


def _numeric(value: object) -> float | None:
    if type(value) not in (int, float):
        return None
    result = float(value)
    if result != result or not -1e8 < result < 1e8:
        return None
    return result


def _age_seconds(checked_at: object, now: datetime) -> float | None:
    if not isinstance(checked_at, str):
        return None
    try:
        timestamp = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return None
    return (now - timestamp.astimezone(UTC)).total_seconds()


def evaluate(
    health: Mapping[str, Any] | None,
    *,
    swap_used_mib: float | None,
    stage_port_free: bool,
    model_size: int | None,
    binary_available: bool,
    mac_arm64: bool,
    now: datetime,
) -> dict[str, object]:
    """Admission is granted only for ALL individually attested safe conditions."""
    reasons: list[str] = []
    if not mac_arm64:
        reasons.append("unexpected_host")
    if not isinstance(health, Mapping):
        reasons.append("governor_unavailable")
        health = {}
    if health.get("status") != "pass":
        reasons.append("governor_unhealthy")
    if health.get("mode") != "normal":
        reasons.append("governor_not_normal")
    age = _age_seconds(health.get("checked_at_utc"), now)
    if age is None or not -5 <= age <= MAX_STATE_AGE_SECONDS:
        reasons.append("governor_stale")
    sample = health.get("sample")
    if not isinstance(sample, Mapping):
        sample = {}
    free = _numeric(sample.get("memory_free"))
    if free is None or free < MIN_FREE_MEMORY_PERCENT or free > 100:
        reasons.append("memory_headroom_low")
    pressure = _numeric(sample.get("pressure"))
    if pressure is None or pressure > 0 or pressure < 0:
        reasons.append("memory_pressure_high_or_unknown")
    cpu_busy = _numeric(sample.get("cpu_busy"))
    if cpu_busy is None or not 0 <= cpu_busy <= 50:
        reasons.append("cpu_busy_or_unknown")
    gpu_busy = _numeric(sample.get("gpu_busy"))
    if gpu_busy is None or not 0 <= gpu_busy <= 60:
        reasons.append("gpu_busy_or_unknown")
    thermal = _numeric(sample.get("thermal"))
    if thermal is None or thermal != 0:
        reasons.append("thermal_warning_or_unknown")
    disk = _numeric(sample.get("disk_free_gib"))
    if disk is None or disk < MIN_DISK_FREE_GIB:
        reasons.append("disk_headroom_low")
    if swap_used_mib is None or not 0 <= swap_used_mib <= MAX_SWAP_USED_MIB:
        reasons.append("swap_used_too_high_or_unknown")
    if not stage_port_free:
        reasons.append("stage_port_in_use")
    if type(model_size) is not int or model_size != EXPECTED_MODEL_BYTES:
        reasons.append("model_identity_size_mismatch")
    if not binary_available:
        reasons.append("staging_binary_unavailable")

    return {
        "admission": "pass" if not reasons else "blocked",
        "reason_codes": sorted(set(reasons)),
        "stage": "isolated_qwen3_embedding_4b_synthetic_only",
        "profile": ISOLATED_PROFILE,
        "live_embedding_server_port": LIVE_PORT,
        "live_embedding_server_touched": False,
        "production_readiness_proven": False,
        "next_action_if_pass": "independent bounded runner and continuous resource guard required",
        "model_launch_executed": False,
    }


def _governor_state() -> Mapping[str, Any] | None:
    # Avoid following a replaced or symlinked path into unrelated files.
    if GOVERNOR.is_symlink() or not GOVERNOR.is_file() or GOVERNOR.stat().st_size > 65536:
        return None
    try:
        raw = json.loads(GOVERNOR.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _swap_mib() -> float | None:
    try:
        output = subprocess.run(
            ["/usr/sbin/sysctl", "vm.swapusage"],
            capture_output=True,
            text=True,
            check=True,
            timeout=3,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"\bused\s*=\s*([0-9]+(?:\.[0-9]+)?)M\b", output)
    return float(match.group(1)) if match else None


def _port_is_free() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", STAGE_PORT))
            return True
        except OSError:
            return False


def live_preflight() -> dict[str, object]:
    try:
        model_bytes = MODEL.stat().st_size if not MODEL.is_symlink() else None
    except OSError:
        model_bytes = None
    return evaluate(
        _governor_state(),
        swap_used_mib=_swap_mib(),
        stage_port_free=_port_is_free(),
        model_size=model_bytes,
        binary_available=BINARY.is_file() and BINARY.stat().st_mode & 0o111 != 0,
        mac_arm64=platform.system() == "Darwin" and platform.machine() == "arm64",
        now=datetime.now(UTC),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", default=True)
    parser.parse_args()
    report = live_preflight()
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if report["admission"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
