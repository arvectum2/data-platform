from pathlib import Path

from arvectum_data.evaluation.sync_efficiency import load_sync_efficiency_suite


def test_repository_sync_efficiency_suite_is_valid():
    suite = load_sync_efficiency_suite(
        Path(__file__).resolve().parents[2] / "benchmarks" / "sync_efficiency_v1.json"
    )
    assert suite.name == "sync-efficiency-v1"
    assert suite.resource_count == 3
    assert [item.expected_changed for item in suite.scenarios] == [0, 1, 3]
    assert [item.expected_indexed for item in suite.scenarios] == [0, 1, 3]
