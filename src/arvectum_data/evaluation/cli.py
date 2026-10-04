from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .core import evaluate_suite
from .http_runner import HttpSearchRunner
from .models import EvaluationSuite


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arvectum-data-eval",
        description="Evaluate Data Platform retrieval against a benchmark JSON file.",
    )
    parser.add_argument("benchmark", type=Path)
    parser.add_argument(
        "--base-url",
        default=os.getenv("ARVECTUM_DATA_EVAL_BASE_URL", "http://127.0.0.1:8094"),
    )
    parser.add_argument(
        "--api-key-env",
        default="ARVECTUM_DATA_EVAL_API_KEY",
        help="Environment variable containing the internal API key.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-top1-below", type=float)
    parser.add_argument("--fail-mrr-below", type=float)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    payload = json.loads(args.benchmark.read_text(encoding="utf-8"))
    suite = EvaluationSuite.from_dict(payload)
    runner = HttpSearchRunner(
        base_url=args.base_url,
        api_key=os.getenv(args.api_key_env, ""),
        timeout_seconds=args.timeout_seconds,
    )
    summary = evaluate_suite(suite, runner)
    result = summary.to_dict()
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")

    if (
        args.fail_top1_below is not None
        and summary.top1_accuracy < args.fail_top1_below
    ):
        return 2
    if args.fail_mrr_below is not None and summary.mrr < args.fail_mrr_below:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
