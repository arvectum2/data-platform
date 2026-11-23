"""Offline-only planning of representative Qwen ingest cohorts.

Never opens a network connection, starts inference, changes the scheduler,
reads production DB or submits a document. Prints numeric synthetic metadata.
"""

from __future__ import annotations

import argparse
import json

from arvectum_data.documents import ingest_bytes

from ingest_slo_shared_qwen_window import synthetic_bytes

TARGETS = (5, 10, 18, 27)


def find_payload(target_chunks: int, seed: int) -> tuple[int, int]:
    if not 1 <= target_chunks <= 100:
        raise ValueError("unsupported chunk target")
    # First size for which the distinct synthetic source reaches the target.
    low, high = 1_000, 120_000

    def chunks_for(size: int) -> tuple[int, int]:
        payload = synthetic_bytes(size, seed)
        result = ingest_bytes(
            payload,
            filename="synthetic.txt",
            collection_id="offline:preflight",
            canonical_uri=f"synthetic://cohort/{seed}",
        )
        return len(result.chunks), len(payload)

    while low < high:
        middle = (low + high) // 2
        actual, _ = chunks_for(middle)
        if actual < target_chunks:
            low = middle + 1
        else:
            high = middle
    actual, payload_bytes = chunks_for(low)
    if actual != target_chunks:
        raise RuntimeError("unable to obtain exact chunk cohort")
    return payload_bytes, actual


def plan() -> dict:
    cohorts = []
    for index, count in enumerate(TARGETS):
        source_bytes, actual = find_payload(count, seed=index + 901)
        cohorts.append(
            {
                "target_chunks": count,
                "actual_chunks": actual,
                "synthetic_bytes_per_document": source_bytes,
                "minimum_samples_per_concurrency_stratum": 20,
            }
        )
    return {
        "mode": "OFFLINE_PREFLIGHT_ONLY",
        "requires_new_authorized_Qwen_window": True,
        "active_model_requests": 0,
        "production_mutations": 0,
        "planned_concurrency_strata": [1, 2],
        "required_observations_all_strata": 20 * len(cohorts) * 2,
        "note": (
            "Future Qwen p95 must be measured separately by chunk size, concurrency, "
            "quality and true enqueue-to-searchable latency. No SLO is inferred here."
        ),
        "cohorts": cohorts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    if not args.check_only:
        parser.error("only offline --check-only mode is permitted")
    print(json.dumps(plan(), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
