"""Prevent another version/dependency drift in a committed lockfile."""
from pathlib import Path

from scripts.check_dependency_lock import check, dependency_name


def test_dependency_lock_matches_project():
    root = Path(__file__).resolve().parents[1]
    assert check(root) == []


def test_normalize_package_names_with_extras():
    assert dependency_name("psycopg[binary]>=3.1,<4.0") == "psycopg"
    assert dependency_name("pydantic-settings>=2.6") == "pydantic-settings"
