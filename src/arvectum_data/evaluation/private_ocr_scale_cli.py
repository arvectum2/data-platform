from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..documents.ocr import TesseractOCRProvider
from .private_ocr_scale import evaluate_private_ocr_scale, load_private_ocr_suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arvectum-data-private-ocr-eval")
    parser.add_argument("suite", type=Path)
    parser.add_argument("--root", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--languages", default="rus+eng")
    parser.add_argument("--dpi", type=int, default=220)
    args = parser.parse_args(argv)

    summary = evaluate_private_ocr_scale(
        load_private_ocr_suite(args.suite),
        roots=tuple(args.root),
        provider=TesseractOCRProvider(languages=args.languages, dpi=args.dpi),
    )
    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if summary["benchmark_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
