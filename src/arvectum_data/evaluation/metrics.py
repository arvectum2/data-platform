from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import log2


def _levenshtein(reference: Sequence[object], hypothesis: Sequence[object]) -> int:
    if len(reference) < len(hypothesis):
        reference, hypothesis = hypothesis, reference

    previous = list(range(len(hypothesis) + 1))
    for ref_index, ref_item in enumerate(reference, start=1):
        current = [ref_index]
        for hyp_index, hyp_item in enumerate(hypothesis, start=1):
            insert_cost = current[hyp_index - 1] + 1
            delete_cost = previous[hyp_index] + 1
            substitute_cost = previous[hyp_index - 1] + (ref_item != hyp_item)
            current.append(min(insert_cost, delete_cost, substitute_cost))
        previous = current
    return previous[-1]


def character_error_rate(reference: str, hypothesis: str) -> float:
    if not reference:
        return 0.0 if not hypothesis else 1.0
    return _levenshtein(tuple(reference), tuple(hypothesis)) / len(reference)


def word_error_rate(reference: str, hypothesis: str) -> float:
    reference_words = tuple(reference.split())
    hypothesis_words = tuple(hypothesis.split())
    if not reference_words:
        return 0.0 if not hypothesis_words else 1.0
    return _levenshtein(reference_words, hypothesis_words) / len(reference_words)


def ndcg_at_k(
    relevance_by_id: Mapping[str, float],
    returned_ids: Sequence[str],
    *,
    k: int = 5,
) -> float:
    if k < 1:
        raise ValueError("k must be positive")

    unique_returned_ids: list[str] = []
    seen_ids: set[str] = set()
    for result_id in returned_ids:
        if result_id in seen_ids:
            continue
        seen_ids.add(result_id)
        unique_returned_ids.append(result_id)
        if len(unique_returned_ids) >= k:
            break

    gains = [
        max(0.0, float(relevance_by_id.get(result_id, 0.0)))
        for result_id in unique_returned_ids
    ]
    dcg = sum(
        ((2.0**gain) - 1.0) / log2(rank + 1)
        for rank, gain in enumerate(gains, start=1)
    )

    ideal_gains = sorted(
        (max(0.0, float(value)) for value in relevance_by_id.values()),
        reverse=True,
    )[:k]
    ideal_dcg = sum(
        ((2.0**gain) - 1.0) / log2(rank + 1)
        for rank, gain in enumerate(ideal_gains, start=1)
    )
    return 0.0 if ideal_dcg == 0.0 else dcg / ideal_dcg


def set_precision_recall(
    expected_ids: Sequence[str],
    actual_ids: Sequence[str],
) -> tuple[float, float]:
    expected = set(expected_ids)
    actual = set(actual_ids)
    if not expected:
        recall = 1.0 if not actual else 0.0
    else:
        recall = len(expected & actual) / len(expected)

    if not actual:
        precision = 1.0 if not expected else 0.0
    else:
        precision = len(expected & actual) / len(actual)
    return precision, recall
