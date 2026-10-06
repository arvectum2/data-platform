import pytest

from arvectum_data.evaluation.runtime_resources import (
    parse_footprint,
    parse_power_snapshot,
)


def test_parse_footprint_uses_physical_not_rss() -> None:
    current, peak = parse_footprint(
        """
Auxiliary data:
    phys_footprint: 1810896104 B
    phys_footprint_peak: 1923519720 B
"""
    )
    assert current == 1810896104
    assert peak == 1923519720


def test_parse_power_snapshot() -> None:
    snapshot = parse_power_snapshot(
        """
CPU Power: 4575 mW
GPU Power: 524 mW
GPU HW active residency: 80.35%
GPU Power: 534 mW
"""
    )
    assert snapshot.cpu_power_mw == 4575
    assert snapshot.gpu_power_mw == pytest.approx(529)
    assert snapshot.gpu_active_residency_percent == pytest.approx(80.35)
