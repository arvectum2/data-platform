"""Aggregate synthetic, *staging-only* ingest phase observations; never contact services.

Input is an allowlisted JSONL numeric trace produced by an independently authorized
synthetic staging run. This tool cannot generate traffic or diagnose production alone.
All phase durations must be exclusive, sequential wall-clock spans in milliseconds.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

PHASES = ("decode_ms", "chunk_ms", "embed_ms", "db_ms")
ALLOWED = frozenset({"synthetic", "bytes", "chunks", "concurrency", "retry_count", "status_code", "total_ms", *PHASES})
MAX_BYTES = 5_000_000
MAX_ROWS = 10_000


def _integer(value: object, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError("invalid numerical measurement")
    return value


def _read_numeric_only(path: Path) -> list[dict[str, int]]:
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("missing or oversized staging trace")
    rows: list[dict[str, int]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            if len(rows) >= MAX_ROWS:
                raise ValueError("too many staging observations")
            try:
                item: Any = json.loads(line)
                if not isinstance(item, dict) or set(item) != ALLOWED or item["synthetic"] is not True:
                    raise ValueError("disallowed trace fields or source")
                numeric = {
                    key: _integer(item[key], minimum=1 if key in {"bytes", "concurrency"} else 0)
                    for key in ALLOWED - {"synthetic"}
                }
                if not 100 <= numeric["status_code"] <= 599:
                    raise ValueError("invalid status code")
                if sum(numeric[name] for name in PHASES) > numeric["total_ms"]:
                    raise ValueError("overlapping or inconsistent phase timings")
                rows.append(numeric)
            except (TypeError, ValueError, KeyError):
                # Never echo original JSON, keys, document titles, or source paths.
                raise ValueError(f"invalid synthetic observation on line {line_number}") from None
    if not rows:
        raise ValueError("no synthetic observations")
    return rows


def _percentile(values: list[int], q: float) -> int:
    values = sorted(values)
    if not values:
        raise ValueError("empty percentile input")
    position = (len(values) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return int(round(values[lower] * (1 - (position - lower)) + values[upper] * (position - lower)))


def _size_bucket(size: int) -> str:
    if size <= 8192:
        return "up_to_8KiB"
    if size <= 65536:
        return "up_to_64KiB"
    if size <= 262144:
        return "up_to_256KiB"
    return "above_256KiB"


def _concurrency_bucket(concurrency: int) -> str:
    return "one" if concurrency == 1 else ("two_to_four" if concurrency <= 4 else "five_plus")


def _summary(rows: list[dict[str, int]]) -> dict[str, object]:
    count = len(rows)
    errors = sum(row["status_code"] >= 400 for row in rows)
    latency_p95 = _percentile([row["total_ms"] for row in rows], 0.95)
    error_rate = errors / count
    # These are the documented DP ingest thresholds, not a new/relaxed SLO.
    if count < 20:
        status = "insufficient-data"
    elif latency_p95 <= 10000 and error_rate <= 0.01:
        status = "green"
    else:
        status = "red"
    phase_p95 = {phase: _percentile([row[phase] for row in rows], 0.95) for phase in PHASES}
    return {
        "status": status,
        "observations": count,
        "error_count": errors,
        "error_rate": round(error_rate, 6),
        "p95_ms": latency_p95,
        "max_ms": max(row["total_ms"] for row in rows),
        "phase_p95_ms": phase_p95,
        "retry_observations": sum(row["retry_count"] > 0 for row in rows),
    }


def analyze(path: Path) -> dict[str, object]:
    rows = _read_numeric_only(path)
    by_size: dict[str, list[dict[str, int]]] = defaultdict(list)
    by_concurrency: dict[str, list[dict[str, int]]] = defaultdict(list)
    by_cell: dict[str, list[dict[str, int]]] = defaultdict(list)
    for row in rows:
        size = _size_bucket(row["bytes"])
        concurrency = _concurrency_bucket(row["concurrency"])
        by_size[size].append(row)
        by_concurrency[concurrency].append(row)
        by_cell[f"{size}__{concurrency}"].append(row)
    return {
        "scope": "synthetic_staging_only",
        "production_slo_proven": False,
        "source_content_included": False,
        "slo_targets": {"ingest_p95_ms": 10000, "max_error_rate": 0.01, "min_samples": 20},
        "overall": _summary(rows),
        "by_input_size": {name: _summary(group) for name, group in sorted(by_size.items())},
        "by_concurrency": {name: _summary(group) for name, group in sorted(by_concurrency.items())},
        "by_size_and_concurrency": {
            name: _summary(group) for name, group in sorted(by_cell.items())
        },
        "note": "Phase comparisons identify hypotheses, not causal root cause or live release acceptance.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-jsonl", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = analyze(args.synthetic_jsonl)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
