from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from arvectum_data.evaluation.adversarial import (
    PostgresAdversarialRunner,
    evaluate_adversarial_suite,
    load_adversarial_suite,
)


pytestmark = pytest.mark.postgres


def test_adversarial_suite_passes_real_postgres_path() -> None:
    database_url = os.getenv("ARVECTUM_DATA_TEST_DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip("ARVECTUM_DATA_TEST_DATABASE_URL is not configured")

    previous = os.environ.get("ARVECTUM_DATA_DATABASE_URL")
    os.environ["ARVECTUM_DATA_DATABASE_URL"] = database_url
    try:
        command.upgrade(Config("alembic.ini"), "head")
        suite = load_adversarial_suite(Path("benchmarks/adversarial_v1.json"))
        summary = evaluate_adversarial_suite(
            suite,
            PostgresAdversarialRunner(database_url=database_url),
        )
    finally:
        if previous is None:
            os.environ.pop("ARVECTUM_DATA_DATABASE_URL", None)
        else:
            os.environ["ARVECTUM_DATA_DATABASE_URL"] = previous

    assert summary.all_passed, summary.to_dict()
    assert summary.pass_rate == 1.0
