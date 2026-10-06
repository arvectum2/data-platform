from __future__ import annotations

from pathlib import Path

from arvectum_data.evaluation.vlm_routing import (
    evaluate_vlm_routing_suite,
    load_vlm_routing_suite,
)


def test_frozen_vlm_routing_separates_layout_stress_from_linear_scan() -> None:
    path = Path(__file__).resolve().parents[2] / "benchmarks" / "vlm_routing_v1.json"
    result = evaluate_vlm_routing_suite(load_vlm_routing_suite(path))

    assert result["routing_accuracy"] == 1.0
    observations = {item["case_id"]: item for item in result["observations"]}
    assert observations["layout-stress-escalates"]["actual_escalation"] is True
    assert observations["layout-stress-escalates"]["actual_reason"] == "ocr-low-confidence"
    assert observations["linear-baseline-stays-ocr"]["actual_escalation"] is False
