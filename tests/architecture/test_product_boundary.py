"""The reusable Data Platform must never directly import Tender Agent business logic."""

from __future__ import annotations

import ast
from pathlib import Path


def test_platform_code_does_not_import_product_modules():
    root = Path(__file__).resolve().parents[2] / "src/arvectum_data"
    forbidden = ("tender_research.", "src.modules.", "src.tender_research.", "ai_corporation.")
    offenders: list[str] = []
    for file in root.rglob("*.py"):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports.append(node.module)
        if any(name.startswith(forbidden) for name in imports):
            offenders.append(str(file.relative_to(root)))
    assert offenders == []
