from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from arvectum_data.evaluation.facts import PostgresFactRunner, load_fact_suite


pytestmark = pytest.mark.postgres


def test_exact_facts_retrieve_expected_sources_top1() -> None:
    database_url = os.getenv("ARVECTUM_DATA_TEST_DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip("ARVECTUM_DATA_TEST_DATABASE_URL is not configured")

    previous = os.environ.get("ARVECTUM_DATA_DATABASE_URL")
    os.environ["ARVECTUM_DATA_DATABASE_URL"] = database_url
    try:
        command.upgrade(Config("alembic.ini"), "head")
        suite = load_fact_suite(Path("benchmarks/fact_preservation_v1.json"))
        summary = PostgresFactRunner(
            database_url=database_url,
            suite=suite,
        ).evaluate()
    finally:
        if previous is None:
            os.environ.pop("ARVECTUM_DATA_DATABASE_URL", None)
        else:
            os.environ["ARVECTUM_DATA_DATABASE_URL"] = previous

    assert summary.chunk_preservation_rate == 1.0
    assert summary.context_preservation_rate == 1.0
    assert summary.retrieval_top1_rate == 1.0, summary.to_dict()
