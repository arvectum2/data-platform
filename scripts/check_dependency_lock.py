"""Detect drift between pyproject.toml and the pinned uv.lock (stdlib only)."""
from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path


def dependency_name(spec: str) -> str:
    """Normalize a PEP-508 direct requirement name, with optional extras."""
    match = re.match(r"^\s*([A-Za-z0-9_.-]+)", spec)
    if match is None:
        raise ValueError(f"invalid dependency declaration: {spec!r}")
    return match.group(1).lower().replace("_", "-").replace(".", "-")


def check(root: Path) -> list[str]:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    matches = [p for p in lock["package"] if p["name"] == project["name"]]
    if len(matches) != 1:
        return ["project package missing or duplicated in uv.lock"]
    current = matches[0]
    findings = []
    if current["version"] != project["version"]:
        findings.append(f"project version: pyproject={project['version']}, lock={current['version']}")
    expected = {dependency_name(dep) for dep in project.get("dependencies", [])}
    actual = {item["name"] for item in current.get("dependencies", [])}
    if expected != actual:
        findings.append(f"core dependency mismatch: only pyproject={sorted(expected - actual)}, only lock={sorted(actual - expected)}")
    project_extras = {
        group: {dependency_name(dep) for dep in deps}
        for group, deps in project.get("optional-dependencies", {}).items()
    }
    lock_extras = {
        group: {item["name"] for item in deps}
        for group, deps in current.get("optional-dependencies", {}).items()
    }
    if project_extras != lock_extras:
        findings.append("optional dependency groups differ from uv.lock")
    return findings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    errors = check(args.root)
    if errors:
        parser.exit(1, "\n".join(errors) + "\nRun `uv lock` to synchronize constraints.\n")
    print("Dependency lock matches project version, direct dependencies and extras.")


if __name__ == "__main__":
    main()
