"""Regression for known 2026 dependency advisories and lockfile provenance."""
from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_locked_package_origins_are_approved() -> None:
    packages = tomllib.loads((ROOT / "uv.lock").read_text())["package"]
    assert len(packages) > 0
    for package in packages:
        source = package["source"]
        assert source == {"registry": "https://pypi.org/simple"} or (
            package["name"] == "arvectum-data" and source == {"editable": "."}
        ), f"unreviewed package source: {package['name']}"


def test_known_security_fixes_are_retained() -> None:
    packages = {
        p["name"]: p["version"]
        for p in tomllib.loads((ROOT / "uv.lock").read_text())["package"]
    }

    def version(name: str) -> tuple[int, ...]:
        return tuple(int(segment) for segment in packages[name].split("."))

    # OSV 2026-11-23: multiple GHSA/PYSEC cryptography disclosures fixed
    # at 48, 49, and 50; pytest tmpdir handling fixed in 9.0.3.
    assert version("cryptography") >= (50, 0, 0)
    assert version("pytest") >= (9, 0, 3)
