from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any, Sequence

try:
    from mlx_vlm import generate, load
    from mlx_vlm.prompt_utils import apply_chat_template
    from mlx_vlm.utils import load_config
except Exception as exc:  # pragma: no cover - optional benchmark dependency
    raise SystemExit(
        "MLX-VLM benchmark dependencies are unavailable. "
        "Install mlx-vlm in a separate benchmark environment."
    ) from exc


_PAGE_MARKER = re.compile(r"\[Page\s+\d+\]\s*", flags=re.IGNORECASE)
_CODE_FENCE = re.compile(r"```(?:text)?|```", flags=re.IGNORECASE)


def _normalize(text: str) -> str:
    text = _CODE_FENCE.sub(" ", text)
    text = _PAGE_MARKER.sub(" ", text)
    return " ".join(text.replace("\u00a0", " ").split())


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


def _extract_first_image(pdf_path: Path, work_dir: Path, artifact_id: str) -> Path:
    prefix = work_dir / artifact_id
    subprocess.run(
        ["pdfimages", "-png", str(pdf_path), str(prefix)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    images = sorted(work_dir.glob(f"{artifact_id}-*.png"))
    if not images:
        raise RuntimeError(f"no embedded PNG extracted from {pdf_path}")
    return images[0]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark a local MLX VLM against frozen scanned-PDF gold text."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--model",
        default="mlx-community/Qwen2.5-VL-3B-Instruct-4bit",
    )
    parser.add_argument("--max-tokens", type=int, default=2500)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--raw-output-dir", type=Path)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    base_dir = args.manifest.parent
    artifacts = [
        item
        for item in manifest["artifacts"]
        if item.get("ocr_required") and item.get("gold_text_file")
    ]
    if not artifacts:
        raise RuntimeError("manifest has no OCR artifacts with gold text")

    prompt = (
        "Transcribe every visible text on this document image exactly. "
        "Preserve the natural reading order. Do not summarize, translate, explain, "
        "add markdown, or omit numbers, dates, identifiers, punctuation, or "
        "table/form labels. Return only the transcription."
    )

    with tempfile.TemporaryDirectory(prefix="arvectum-vlm-bench-") as tmp:
        work_dir = Path(tmp)
        images = {
            item["id"]: _extract_first_image(
                base_dir / item["file"],
                work_dir,
                item["id"],
            )
            for item in artifacts
        }

        load_started = time.perf_counter()
        model, processor = load(args.model)
        config = load_config(args.model)
        load_ms = (time.perf_counter() - load_started) * 1000.0

        first_id = artifacts[0]["id"]
        warm_prompt = apply_chat_template(
            processor,
            config,
            "Look at the document and answer only OK.",
            num_images=1,
        )
        warm_started = time.perf_counter()
        generate(
            model,
            processor,
            warm_prompt,
            image=[str(images[first_id])],
            max_tokens=4,
            temperature=0.0,
            verbose=False,
        )
        warmup_ms = (time.perf_counter() - warm_started) * 1000.0

        results: list[dict[str, Any]] = []
        for artifact in artifacts:
            artifact_id = artifact["id"]
            formatted_prompt = apply_chat_template(
                processor,
                config,
                prompt,
                num_images=1,
            )
            started = time.perf_counter()
            output = generate(
                model,
                processor,
                formatted_prompt,
                image=[str(images[artifact_id])],
                max_tokens=args.max_tokens,
                temperature=0.0,
                verbose=False,
            )
            latency_ms = (time.perf_counter() - started) * 1000.0

            hypothesis = _normalize(output.text)
            reference = _normalize(
                (base_dir / artifact["gold_text_file"]).read_text(encoding="utf-8")
            )
            missing = [
                fragment
                for fragment in artifact.get("required_text", [])
                if _normalize(fragment) not in hypothesis
            ]

            if args.raw_output_dir is not None:
                args.raw_output_dir.mkdir(parents=True, exist_ok=True)
                (args.raw_output_dir / f"{artifact_id}.txt").write_text(
                    output.text,
                    encoding="utf-8",
                )

            results.append(
                {
                    "artifact_id": artifact_id,
                    "latency_ms": latency_ms,
                    "cer": _cer(reference, hypothesis),
                    "wer": _wer(reference, hypothesis),
                    "required_text_passed": not missing,
                    "missing_required_text": missing,
                    "gold_chars": len(reference),
                    "output_chars": len(hypothesis),
                    "prompt_tokens": int(output.prompt_tokens),
                    "generation_tokens": int(output.generation_tokens),
                    "generation_tps": float(output.generation_tps),
                    "peak_memory_gb": float(output.peak_memory),
                    "finish_reason": output.finish_reason,
                }
            )

    summary = {
        "reference": "MLX-VLM",
        "versions": {
            "mlx_vlm": _package_version("mlx-vlm"),
            "mlx": _package_version("mlx"),
        },
        "model": args.model,
        "manifest": str(args.manifest),
        "load_ms": load_ms,
        "warmup_ms": warmup_ms,
        "cases": len(results),
        "required_text_pass_rate": (
            sum(1 for item in results if item["required_text_passed"])
            / len(results)
        ),
        "mean_cer": sum(float(item["cer"]) for item in results) / len(results),
        "mean_wer": sum(float(item["wer"]) for item in results) / len(results),
        "mean_latency_ms": (
            sum(float(item["latency_ms"]) for item in results) / len(results)
        ),
        "max_peak_memory_gb": max(
            float(item["peak_memory_gb"]) for item in results
        ),
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
