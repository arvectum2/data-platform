from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..modes import ExecutionMode, mode_profile


@dataclass(frozen=True, slots=True)
class ModeBudgetObservation:
    mode: ExecutionMode
    p95_latency_ms: float
    model_calls: int
    physical_footprint_bytes: int
    network_discovery_used: bool = False


@dataclass(frozen=True, slots=True)
class ModeBudgetResult:
    mode: ExecutionMode
    passed: bool
    latency_passed: bool
    model_calls_passed: bool
    footprint_passed: bool
    network_passed: bool

    def to_dict(self) -> dict[str, Any]:
        profile = mode_profile(self.mode)
        return {
            "mode": self.mode.value,
            "passed": self.passed,
            "checks": {
                "latency_passed": self.latency_passed,
                "model_calls_passed": self.model_calls_passed,
                "footprint_passed": self.footprint_passed,
                "network_passed": self.network_passed,
            },
            "budgets": {
                "p95_latency_budget_ms": profile.p95_latency_budget_ms,
                "max_model_calls": profile.max_model_calls,
                "max_physical_footprint_bytes": profile.max_physical_footprint_bytes,
                "network_discovery": profile.network_discovery,
            },
        }


def evaluate_mode_budget(observation: ModeBudgetObservation) -> ModeBudgetResult:
    profile = mode_profile(observation.mode)
    latency_passed = observation.p95_latency_ms <= profile.p95_latency_budget_ms
    model_calls_passed = observation.model_calls <= profile.max_model_calls
    footprint_passed = (
        observation.physical_footprint_bytes
        <= profile.max_physical_footprint_bytes
    )
    network_passed = (
        profile.network_discovery or not observation.network_discovery_used
    )
    return ModeBudgetResult(
        mode=observation.mode,
        passed=(
            latency_passed
            and model_calls_passed
            and footprint_passed
            and network_passed
        ),
        latency_passed=latency_passed,
        model_calls_passed=model_calls_passed,
        footprint_passed=footprint_passed,
        network_passed=network_passed,
    )
