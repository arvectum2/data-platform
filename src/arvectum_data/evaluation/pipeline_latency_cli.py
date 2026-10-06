from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline_latency import build_pipeline_latency_report, load_json


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arvectum-data-latency-report",
        description="Aggregate per-stage p50/p95/max from benchmark result JSON files.",
    )
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--retrieval", required=True, type=Path)
    parser.add_argument("--faithfulness", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = build_pipeline_latency_report(
        corpus=load_json(args.corpus),
        retrieval=load_json(args.retrieval),
        faithfulness=load_json(args.faithfulness),
    )
    rendered = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
