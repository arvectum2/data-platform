from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..documents.ocr import TesseractOCRProvider
from .corpus import evaluate_corpus


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arvectum-data-corpus-eval",
        description="Evaluate extraction/OCR against a frozen Data Platform corpus.",
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--ocr-provider",
        choices=("disabled", "tesseract"),
        default="disabled",
    )
    parser.add_argument("--ocr-languages", default="rus+eng")
    parser.add_argument("--ocr-dpi", type=int, default=220)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-ingestion-below", type=float)
    parser.add_argument("--fail-benchmark-below", type=float)
    parser.add_argument("--fail-ocr-cer-above", type=float)
    parser.add_argument("--fail-ocr-wer-above", type=float)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    provider = None
    include_ocr = args.ocr_provider != "disabled"
    if args.ocr_provider == "tesseract":
        provider = TesseractOCRProvider(
            languages=args.ocr_languages,
            dpi=args.ocr_dpi,
        )

    summary = evaluate_corpus(
        args.manifest,
        include_ocr=include_ocr,
        ocr_provider=provider,
    )
    rendered = json.dumps(summary.to_dict(), ensure_ascii=False, indent=2)
    print(rendered)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")

    if (
        args.fail_ingestion_below is not None
        and summary.ingestion_success_rate < args.fail_ingestion_below
    ):
        return 2
    if (
        args.fail_benchmark_below is not None
        and summary.benchmark_success_rate < args.fail_benchmark_below
    ):
        return 5
    if args.fail_ocr_cer_above is not None:
        if summary.mean_cer is None or summary.mean_cer > args.fail_ocr_cer_above:
            return 3
    if args.fail_ocr_wer_above is not None:
        if summary.mean_wer is None or summary.mean_wer > args.fail_ocr_wer_above:
            return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
