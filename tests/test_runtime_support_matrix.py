"""Guard the declared runtime baseline and compatibility CI coverage."""

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_default_python_matches_supported_universal_lock() -> None:
    assert (ROOT / ".python-version").read_text().strip() == "3.14"
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    assert project["project"]["requires-python"] == ">=3.11"
    assert lock["requires-python"] == project["project"]["requires-python"]
    sdk = tomllib.loads((ROOT / "sdk/python/pyproject.toml").read_text())
    assert sdk["project"]["requires-python"] == ">=3.11"


def test_ci_covers_legacy_and_current_python_node() -> None:
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    python_matrix = re.search(r'python-version:\s*\[([^]]+)\]', ci)
    node_matrix = re.search(r'node-version:\s*\[([^]]+)\]', ci)
    assert python_matrix is not None
    assert node_matrix is not None
    assert set(re.findall(r'"([^"]+)"', python_matrix.group(1))) >= {
        "3.11", "3.12", "3.13", "3.14", "3.15"
    }
    assert set(re.findall(r'"([^"]+)"', node_matrix.group(1))) >= {
        "20", "22", "24", "26"
    }
    assert 'node-version: ${{ matrix.node-version }}' in ci
    assert "actions/checkout@v7.0.1" in ci
    assert "actions/setup-node@v7.1.0" in ci
    assert "actions/setup-python@v7.1.0" in ci
    assert "locked-reproducibility:" in ci
    assert "uv sync --python 3.14 --frozen --extra dev" in ci
    package = json.loads((ROOT / "package.json").read_text())
    assert package["engines"]["node"] == ">=18"
