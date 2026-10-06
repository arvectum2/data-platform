from pathlib import Path

from arvectum_data.evaluation.multi_hop import load_multi_hop_suite


def test_repository_multi_hop_suite_is_valid() -> None:
    suite = load_multi_hop_suite(
        Path(__file__).resolve().parents[2] / "benchmarks" / "multi_hop_v1.json"
    )
    assert suite.name == "multi-hop-v1"
    assert [item.expected_target_depth for item in suite.scenarios] == [2, 2, 3]
    assert all(item.expected_evidence_edges >= 2 for item in suite.scenarios)
