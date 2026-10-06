from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..api.config import Settings
from .private_runtime import evaluate_private_runtime


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arvectum-data-private-eval",
        description="Audit whether the configured core Data Platform path is local/private.",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-coverage-below", type=float, default=1.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = evaluate_private_runtime(Settings())
    rendered = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report.coverage >= args.fail_coverage_below else 2


if __name__ == "__main__":
    raise SystemExit(main())
