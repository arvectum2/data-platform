from __future__ import annotations

import argparse
import json
import re
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any, Sequence

try:
    from unstructured.partition.auto import partition
    from unstructured.partition.pdf import partition_pdf
except Exception as exc:  # pragma: no cover - optional benchmark dependency
    raise SystemExit(
        "Unstructured benchmark dependencies are unavailable. "
        "Install them in a separate benchmark environment, for example: "
        "uv pip install 'unstructured[pdf,docx,xlsx]'"
    ) from exc


_PAGE_MARKER = re.compile(r"\[Page\s+\d+\]\s*", flags=re.IGNORECASE)


def _normalize(text: str) -> str:
    text = _PAGE_MARKER.sub(" ", text)
    text = text.replace("\u00a0", " ")
    return " ".join(text.split())


def _levenshtein(reference: Sequence[object], hypothesis: Sequence[object]) -> int:
    if len(reference) < len(hypothesis):
        reference, hypothesis = hypothesis, reference
    previous = list(range(len(hypothesis) + 1))
    for ref_index, ref_item in enumerate(reference, start=1):
        current = [ref_index]
        for hyp_index, hyp_item in enumerate(hypothesis, start=1):
            current.append(
                min(
                    current[hyp_index - 1] + 1,
                    previous[hyp_index] + 1,
                    previous[hyp_index - 1] + (ref_item != hyp_item),
                )
            )
        previous = current
    return previous[-1]


def _cer(reference: str, hypothesis: str) -> float:
    if not reference:
        return 0.0 if not hypothesis else 1.0
    return _levenshtein(tuple(reference), tuple(hypothesis)) / len(reference)


def _wer(reference: str, hypothesis: str) -> float:
    reference_words = tuple(reference.split())
    hypothesis_words = tuple(hypothesis.split())
    if not reference_words:
        return 0.0 if not hypothesis_words else 1.0
    return _levenshtein(reference_words, hypothesis_words) / len(reference_words)


def _package_version(name: str) -> str:
    try:
        return version(name)
    except Exception:
        return ""


def _partition_artifact(path: Path, *, ocr_required: bool):
    if ocr_required:
        return partition_pdf(
            filename=str(path),
            strategy="ocr_only",
            languages=["rus", "eng"],
        )
    return partition(
        filename=str(path),
        languages=["rus", "eng"],
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Unstructured against the frozen Data Platform corpus."
    )
    parser.add_argument(
        "manifest",
        type=Path,
        help="Path to a corpus manifest.json file.",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    base_dir = args.manifest.parent
    results: list[dict[str, Any]] = []

    for artifact in manifest["artifacts"]:
        path = base_dir / artifact["file"]
        started = time.perf_counter()
        try:
            elements = _partition_artifact(
                path,
                ocr_required=bool(artifact.get("ocr_required")),
            )
            latency_ms = (time.perf_counter() - started) * 1000.0
            text = "\n".join(
                getattr(element, "text", "") or ""
                for element in elements
            )
            normalized_text = _normalize(text)
            missing = [
                fragment
                for fragment in artifact.get("required_text", [])
                if _normalize(fragment) not in normalized_text
            ]
            passed = (
                not missing
                and len(normalized_text) >= int(artifact.get("min_text_chars", 1))
            )
            result: dict[str, Any] = {
                "artifact_id": artifact["id"],
                "format": artifact["format"],
                "ocr_required": bool(artifact.get("ocr_required")),
                "passed": passed,
                "elements": len(elements),
                "text_chars": len(text),
                "missing_required_text": missing,
                "latency_ms": latency_ms,
            }
            if artifact.get("gold_text_file"):
                gold = (base_dir / artifact["gold_text_file"]).read_text(
                    encoding="utf-8"
                )
                reference = _normalize(gold)
                hypothesis = normalized_text
                result["cer"] = _cer(reference, hypothesis)
                result["wer"] = _wer(reference, hypothesis)
            results.append(result)
        except Exception as exc:
            results.append(
                {
                    "artifact_id": artifact["id"],
                    "format": artifact["format"],
                    "ocr_required": bool(artifact.get("ocr_required")),
                    "passed": False,
                    "latency_ms": (time.perf_counter() - started) * 1000.0,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )

    native = [item for item in results if not item["ocr_required"]]
    ocr = [item for item in results if item["ocr_required"]]
    successful_ocr = [
        item
        for item in ocr
        if "cer" in item and "wer" in item
    ]

    def rate(items: list[dict[str, Any]]) -> float:
        if not items:
            return 0.0
        return sum(1 for item in items if item["passed"]) / len(items)

    summary = {
        "reference": "Unstructured",
        "versions": {
            "unstructured": _package_version("unstructured"),
            "unstructured_pytesseract": _package_version(
                "unstructured.pytesseract"
            ),
            "unstructured_inference": _package_version(
                "unstructured-inference"
            ),
        },
        "manifest": str(args.manifest),
        "artifacts": len(results),
        "pass_rate": rate(results),
        "native_pass_rate": rate(native),
        "ocr_pass_rate": rate(ocr),
        "ocr_mean_cer": (
            sum(float(item["cer"]) for item in successful_ocr)
            / len(successful_ocr)
            if successful_ocr
            else None
        ),
        "ocr_mean_wer": (
            sum(float(item["wer"]) for item in successful_ocr)
            / len(successful_ocr)
            if successful_ocr
            else None
        ),
        "latency_ms_total": sum(float(item["latency_ms"]) for item in results),
        "results": results,
    }

    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
