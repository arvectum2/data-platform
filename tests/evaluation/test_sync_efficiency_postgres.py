import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from arvectum_data.evaluation.sync_efficiency import (
    PostgresSyncEfficiencyRunner,
    load_sync_efficiency_suite,
)


pytestmark = pytest.mark.postgres


def test_incremental_sync_reindexes_only_changed_resources():
    database_url = os.getenv("ARVECTUM_DATA_TEST_DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip("ARVECTUM_DATA_TEST_DATABASE_URL is not configured")

    previous = os.environ.get("ARVECTUM_DATA_DATABASE_URL")
    os.environ["ARVECTUM_DATA_DATABASE_URL"] = database_url
    try:
        command.upgrade(Config("alembic.ini"), "head")
        suite = load_sync_efficiency_suite(Path("benchmarks/sync_efficiency_v1.json"))
        summary = PostgresSyncEfficiencyRunner(
            database_url=database_url,
            suite=suite,
        ).run()
    finally:
        if previous is None:
            os.environ.pop("ARVECTUM_DATA_DATABASE_URL", None)
        else:
            os.environ["ARVECTUM_DATA_DATABASE_URL"] = previous

    assert summary.pass_rate == 1.0, summary.to_dict()
    assert summary.unnecessary_indexed_resources == 0
    assert summary.total_changed_resources == 4
    assert summary.total_indexed_resources == 4
    assert summary.indexing_amplification == 1.0
