from arvectum_data.evaluation.mode_budgets import (
    ModeBudgetObservation,
    evaluate_mode_budget,
)
from arvectum_data.modes import ExecutionMode, mode_profile


def test_mode_profiles_expose_operational_budgets() -> None:
    fast = mode_profile(ExecutionMode.FAST)
    standard = mode_profile(ExecutionMode.STANDARD)
    deep = mode_profile(ExecutionMode.DEEP)
    research = mode_profile(ExecutionMode.RESEARCH)

    assert fast.p95_latency_budget_ms == 250
    assert standard.p95_latency_budget_ms == 750
    assert deep.p95_latency_budget_ms == 5000
    assert research.p95_latency_budget_ms == 20000
    assert fast.max_model_calls == 0
    assert research.max_model_calls == 3


def test_fast_budget_accepts_measured_core_retrieval() -> None:
    result = evaluate_mode_budget(
        ModeBudgetObservation(
            mode=ExecutionMode.FAST,
            p95_latency_ms=128.5,
            model_calls=0,
            physical_footprint_bytes=2_000_000_000,
        )
    )
    assert result.passed is True


def test_standard_rejects_current_local_llm_rerank_latency() -> None:
    result = evaluate_mode_budget(
        ModeBudgetObservation(
            mode=ExecutionMode.STANDARD,
            p95_latency_ms=5000.0,
            model_calls=1,
            physical_footprint_bytes=12_000_000_000,
        )
    )
    assert result.passed is False
    assert result.latency_passed is False


def test_non_research_modes_reject_network_discovery() -> None:
    result = evaluate_mode_budget(
        ModeBudgetObservation(
            mode=ExecutionMode.DEEP,
            p95_latency_ms=1000.0,
            model_calls=1,
            physical_footprint_bytes=12_000_000_000,
            network_discovery_used=True,
        )
    )
    assert result.passed is False
    assert result.network_passed is False
