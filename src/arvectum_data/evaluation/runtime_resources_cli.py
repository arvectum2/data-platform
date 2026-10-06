from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..api.config import Settings
from .models import EvaluationSuite
from .runtime_resources import collect_runtime_resources


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arvectum-data-resource-eval",
        description="Measure Mac runtime physical footprint and search throughput.",
    )
    parser.add_argument("benchmark", type=Path)
    parser.add_argument("--consumer", default="")
    parser.add_argument("--workers", default="1,4,8")
    parser.add_argument("--service-port", type=int, default=8094)
    parser.add_argument("--embedding-port", type=int, default=8090)
    parser.add_argument("--reasoning-port", type=int, default=8081)
    parser.add_argument("--sample-power", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    workers = tuple(int(item) for item in args.workers.split(",") if item.strip())
    if not workers or any(item < 1 for item in workers):
        raise SystemExit("--workers must contain positive integers")
    suite = EvaluationSuite.from_dict(
        json.loads(args.benchmark.read_text(encoding="utf-8"))
    )
    report = collect_runtime_resources(
        Settings(),
        suite,
        consumer=args.consumer or None,
        workers=workers,
        service_port=args.service_port,
        embedding_port=args.embedding_port,
        reasoning_port=args.reasoning_port,
        sample_power=args.sample_power,
    )
    rendered = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
