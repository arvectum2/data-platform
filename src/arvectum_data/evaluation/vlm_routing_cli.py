from __future__ import annotations

import argparse
import json
from pathlib import Path

from .vlm_routing import evaluate_vlm_routing_suite, load_vlm_routing_suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arvectum-data-vlm-routing-eval",
        description="Evaluate frozen OCR-to-VLM escalation routing.",
    )
    parser.add_argument("benchmark", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-accuracy-below", type=float, default=1.0)
    args = parser.parse_args(argv)

    result = evaluate_vlm_routing_suite(load_vlm_routing_suite(args.benchmark))
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if result["routing_accuracy"] >= args.fail_accuracy_below else 2


if __name__ == "__main__":
    raise SystemExit(main())
