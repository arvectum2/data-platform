"""Deterministic stdlib-only architectural audit of every platform Python module.

No file imports/execution and no external network calls. Findings are candidates
for human review, not claims that a source file has been manually optimized.
"""
from __future__ import annotations

import argparse
import ast
import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


_CONTROL = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.ExceptHandler, ast.Assert, ast.Match)


@dataclass(frozen=True)
class ModuleAudit:
    module: str
    layer: str
    lines: int
    functions: int
    classes: int
    max_function_lines: int
    max_decisions: int
    broad_excepts: int
    subprocess_calls: int
    external_imports: str
    priority: str
    recommendation: str


def audit_file(path: Path, root: Path) -> ModuleAudit:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    relative = path.relative_to(root).with_suffix("")
    module = ".".join(relative.parts)
    layer = relative.parts[0] if len(relative.parts) > 1 else "root"
    lines = len(path.read_text(encoding="utf-8").splitlines())
    functions = [x for x in ast.walk(tree) if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))]
    classes = [x for x in ast.walk(tree) if isinstance(x, ast.ClassDef)]
    max_function_lines = max((getattr(x, "end_lineno", x.lineno) - x.lineno + 1 for x in functions), default=0)
    max_decisions = max((sum(isinstance(n, _CONTROL) for n in ast.walk(x)) + sum(max(0, len(n.values) - 1) for n in ast.walk(x) if isinstance(n, ast.BoolOp)) for x in functions), default=0)
    broad_excepts = sum(
        isinstance(x, ast.ExceptHandler) and (x.type is None or isinstance(x.type, ast.Name) and x.type.id in {"Exception", "BaseException"})
        for x in ast.walk(tree)
    )
    subprocess_calls = sum(
        isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute)
        and isinstance(x.func.value, ast.Name) and x.func.value.id == "subprocess"
        for x in ast.walk(tree)
    )
    imports: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in n.names)
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            imports.add(n.module.split(".")[0])
    from sys import stdlib_module_names
    third_party = sorted(i for i in imports if i not in stdlib_module_names and i not in {"arvectum_data", "__future__"})
    flags = []
    if lines >= 500:
        flags.append("large-module")
    if max_function_lines >= 150:
        flags.append("long-function")
    if max_decisions >= 30:
        flags.append("high-branching")
    if broad_excepts >= 3:
        flags.append("broad-errors")
    if subprocess_calls:
        flags.append("external-process")
    if not flags:
        flags.append("preserve; inspect interface/test contract on changes")
    if lines >= 600 or max_function_lines >= 200 or max_decisions >= 40:
        priority = "P1"
    elif lines >= 350 or max_function_lines >= 100 or max_decisions >= 20 or broad_excepts >= 3:
        priority = "P2"
    else:
        priority = "P3"
    return ModuleAudit(
        module=module, layer=layer, lines=lines, functions=len(functions), classes=len(classes),
        max_function_lines=max_function_lines, max_decisions=max_decisions,
        broad_excepts=broad_excepts, subprocess_calls=subprocess_calls,
        external_imports=", ".join(third_party), priority=priority,
        recommendation="; ".join(flags),
    )


def collect(root: Path) -> list[ModuleAudit]:
    return [audit_file(path, root) for path in sorted(root.rglob("*.py")) if "__pycache__" not in path.parts]


def export(rows: list[ModuleAudit], csv_path: Path, summary_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=list(ModuleAudit.__dataclass_fields__), lineterminator="\n"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: getattr(row, field) for field in ModuleAudit.__dataclass_fields__})
    priorities = Counter(row.priority for row in rows)
    layers = Counter(row.layer for row in rows)
    lines = sum(row.lines for row in rows)
    md = [
        "# Data Platform — complete module inventory and static review",
        "",
        "The CSV beside this document contains **one individually analyzed row for every Python source module**.",
        "Metrics are obtained by parsing the AST without importing code. Recommendations are **review candidates**, not proof of an optimization or benchmark improvement.",
        "",
        f"- Modules: **{len(rows)}**; total source lines: **{lines}**",
        f"- Priorities: P1 **{priorities['P1']}**, P2 **{priorities['P2']}**, P3 **{priorities['P3']}**",
        "- P1: source >=600 lines, function >=200 lines or complex function >=40 decisions; P2: smaller but still large or broad-exception hotspots.",
        "- `max_decisions` is a rough AST-based branching proxy, not a formal cyclomatic complexity measurement.",
        "",
        "## Modules by responsibility",
        "",
        "| Layer | Modules |",
        "|---|---:|",
    ]
    md += [f"| `{name}` | {count} |" for name, count in sorted(layers.items())]
    md += ["", "## Highest-priority individual reviews", "", "| Module | Lines | Longest function | Branches | Exception handlers |", "|---|---:|---:|---:|---:|"]
    for item in sorted([row for row in rows if row.priority == "P1"], key=lambda row: (-row.lines, row.module)):
        md.append(f"| `{item.module}` | {item.lines} | {item.max_function_lines} | {item.max_decisions} | {item.broad_excepts} |")
    md += ["", "## Reproduce", "", "`python scripts/audit_modules.py`", "", "A P3 classification means no obvious size/branching red flag was detected; it does not mean a module has been functionally or performance-validated.", ""]
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("\n".join(md), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("src/arvectum_data"))
    parser.add_argument("--csv", type=Path, default=Path("docs/audits/module_inventory.csv"))
    parser.add_argument("--summary", type=Path, default=Path("docs/audits/module_inventory.md"))
    args = parser.parse_args()
    rows = collect(args.root)
    export(rows, args.csv, args.summary)
    print(f"Audited {len(rows)} modules: " + ", ".join(f"{key}: {sum(x.priority == key for x in rows)}" for key in ("P1", "P2", "P3")))


if __name__ == "__main__":
    main()
