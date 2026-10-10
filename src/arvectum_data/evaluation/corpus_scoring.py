"""Pure reproducible structure and OCR-text scoring for frozen document corpora.

No document IO, OCR engine calls, network, ML model state or side effects.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

_PAGE_MARKER = re.compile(r"\[Page\s+\d+\]\s*", flags=re.IGNORECASE)


def _normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    return " ".join(text.split())


def _normalize_for_ocr(text: str) -> str:
    return _normalize_text(_PAGE_MARKER.sub(" ", text))


def _normalized_lines(text: str) -> tuple[str, ...]:
    return tuple(
        _normalize_text(line)
        for line in text.splitlines()
        if _normalize_text(line)
    )


def _row_cells(line: str) -> tuple[str, ...]:
    return tuple(_normalize_text(cell) for cell in line.split("\t") if _normalize_text(cell))


def _contains_ordered_cells(actual: tuple[str, ...], expected: tuple[str, ...]) -> bool:
    position = 0
    for expected_cell in expected:
        normalized_expected = _normalize_text(expected_cell)
        while position < len(actual):
            if normalized_expected in actual[position]:
                position += 1
                break
            position += 1
        else:
            return False
    return True


def _structure_score(
    text: str,
    *,
    required_rows: tuple[tuple[str, ...], ...],
    required_fields: tuple[tuple[str, str], ...],
) -> tuple[float | None, int, int]:
    checks: list[bool] = []
    tabular_rows = tuple(_row_cells(line) for line in text.splitlines() if "\t" in line)

    for expected_row in required_rows:
        checks.append(
            any(
                _contains_ordered_cells(actual_row, expected_row)
                for actual_row in tabular_rows
            )
        )

    normalized_text = _normalize_text(text)
    for label, value in required_fields:
        normalized_label = _normalize_text(label)
        normalized_value = _normalize_text(value)
        label_index = normalized_text.find(normalized_label)
        value_index = normalized_text.find(normalized_value, max(0, label_index))
        checks.append(label_index >= 0 and value_index >= label_index)

    if not checks:
        return None, 0, 0
    matched = sum(1 for item in checks if item)
    return matched / len(checks), matched, len(checks)


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction
