import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from arvectum_data.evaluation.multi_hop import (
    PostgresMultiHopRunner,
    load_multi_hop_suite,
)


pytestmark = pytest.mark.postgres


def test_multi_hop_graph_retrieval_preserves_edge_evidence() -> None:
    database_url = os.getenv("ARVECTUM_DATA_TEST_DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip("ARVECTUM_DATA_TEST_DATABASE_URL is not configured")

    previous = os.environ.get("ARVECTUM_DATA_DATABASE_URL")
    os.environ["ARVECTUM_DATA_DATABASE_URL"] = database_url
    try:
        command.upgrade(Config("alembic.ini"), "head")
        summary = PostgresMultiHopRunner(
            database_url=database_url,
            suite=load_multi_hop_suite(Path("benchmarks/multi_hop_v1.json")),
        ).run()
    finally:
        if previous is None:
            os.environ.pop("ARVECTUM_DATA_DATABASE_URL", None)
        else:
            os.environ["ARVECTUM_DATA_DATABASE_URL"] = previous

    assert summary.pass_rate == 1.0, summary.to_dict()
    assert summary.target_recall == 1.0
    assert summary.provenance_completeness == 1.0
