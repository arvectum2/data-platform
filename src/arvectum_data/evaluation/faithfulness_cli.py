from __future__ import annotations

import argparse
import json
from pathlib import Path

from .faithfulness import (
    build_local_provider,
    evaluate_faithfulness_suite,
    load_faithfulness_suite,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arvectum-data-faithfulness-eval",
        description="Evaluate local answer synthesis against frozen faithfulness cases.",
    )
    parser.add_argument("suite", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8081/v1")
    parser.add_argument("--model-version")
    parser.add_argument("--timeout-seconds", type=float, default=75.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-pass-rate-below", type=float, default=1.0)
    parser.add_argument("--fail-citation-precision-below", type=float, default=1.0)
    parser.add_argument("--fail-citation-recall-below", type=float, default=1.0)
    parser.add_argument("--fail-support-below", type=float, default=1.0)
    parser.add_argument("--fail-abstention-below", type=float, default=1.0)
    parser.add_argument("--fail-contradiction-below", type=float, default=1.0)
    parser.add_argument("--fail-answer-terms-below", type=float, default=1.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    summary = evaluate_faithfulness_suite(
        load_faithfulness_suite(args.suite),
        build_local_provider(
            model=args.model,
            base_url=args.base_url,
            version=args.model_version,
            timeout_seconds=args.timeout_seconds,
        ),
    )
    rendered = json.dumps(summary.to_dict(), ensure_ascii=False, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")

    checks = (
        (summary.pass_rate, args.fail_pass_rate_below, 2),
        (summary.citation_precision, args.fail_citation_precision_below, 3),
        (summary.citation_recall, args.fail_citation_recall_below, 4),
        (summary.claim_support_rate, args.fail_support_below, 5),
        (summary.abstention_accuracy, args.fail_abstention_below, 6),
        (summary.contradiction_recall, args.fail_contradiction_below, 7),
        (summary.answer_term_recall, args.fail_answer_terms_below, 8),
    )
    for observed, threshold, code in checks:
        if observed < threshold:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
