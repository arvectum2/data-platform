from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .http_runner import HttpSearchRunner
from .models import EvaluationSuite
from .query_expansion_compare import compare_query_expansion


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arvectum-data-query-expansion-eval",
        description="Compare base retrieval with automatic query expansion.",
    )
    parser.add_argument("benchmark", type=Path)
    parser.add_argument(
        "--base-url",
        default=os.getenv("ARVECTUM_DATA_EVAL_BASE_URL", "http://127.0.0.1:8094"),
    )
    parser.add_argument("--api-key-env", default="ARVECTUM_DATA_EVAL_API_KEY")
    parser.add_argument("--consumer", default=os.getenv("ARVECTUM_DATA_EVAL_CONSUMER", ""))
    parser.add_argument("--consumer-key-env", default="ARVECTUM_DATA_EVAL_CONSUMER_KEY")
    parser.add_argument("--baseline-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--expanded-timeout-seconds", type=float, default=15.0)
    parser.add_argument("--query-expansion-limit", type=int, default=3)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.query_expansion_limit < 1 or args.query_expansion_limit > 8:
        raise SystemExit("--query-expansion-limit must be between 1 and 8")

    suite = EvaluationSuite.from_dict(
        json.loads(args.benchmark.read_text(encoding="utf-8"))
    )
    common = {
        "base_url": args.base_url,
        "api_key": os.getenv(args.api_key_env, ""),
        "consumer": args.consumer,
        "consumer_key": os.getenv(args.consumer_key_env, ""),
    }
    comparison = compare_query_expansion(
        suite,
        baseline_runner=HttpSearchRunner(
            **common,
            timeout_seconds=args.baseline_timeout_seconds,
        ),
        expanded_runner=HttpSearchRunner(
            **common,
            timeout_seconds=args.expanded_timeout_seconds,
            expand_query=True,
            query_expansion_limit=args.query_expansion_limit,
        ),
    )
    rendered = json.dumps(comparison.to_dict(), ensure_ascii=False, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if comparison.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
