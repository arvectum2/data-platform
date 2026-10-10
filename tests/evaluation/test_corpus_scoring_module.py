"""Frozen corpus scoring stays deterministic and preserves Cyrillic tables."""

import pytest

from arvectum_data.evaluation import corpus
from arvectum_data.evaluation.corpus_scoring import (
    _normalize_for_ocr,
    _percentile,
    _structure_score,
)


def test_old_metric_facades_preserved():
    assert corpus._structure_score is _structure_score
    assert corpus._percentile is _percentile
    assert corpus._normalize_for_ocr is _normalize_for_ocr


def test_russian_ocr_page_markers_removed_without_hiding_text():
    assert _normalize_for_ocr("[Page 1] Поставка\u00a0оборудования   [Page 2] по контракту") == (
        "Поставка оборудования по контракту"
    )


def test_source_table_cells_must_match_in_order():
    text = "Извещение\n№\tТовар\tЦена\n1\tМонитор\t15000\n"
    assert _structure_score(
        text, required_rows=(("Товар", "Цена"), ("Монитор", "15000")),
        required_fields=(("Извещение", "№"),),
    ) == (1.0, 3, 3)
    assert _structure_score(
        text, required_rows=(("Цена", "Товар"),),
        required_fields=(),
    ) == (0.0, 0, 1)


def test_missing_requirements_are_not_imagined():
    assert _structure_score("ТЗ", required_rows=(), required_fields=()) == (None, 0, 0)
    assert _structure_score(
        "ТЗ", required_rows=(), required_fields=(("Дата", "неизвестно"),),
    ) == (0.0, 0, 1)


@pytest.mark.parametrize(("values", "p", "expected"), [
    ([], 0.95, 0.0),
    ([8.0], 0.95, 8.0),
    ([0.0, 10.0], 0.5, 5.0),
    ([0.0, 10.0, 20.0], 0.75, 15.0),
])
def test_bounded_latency_percentiles(values, p, expected):
    assert _percentile(values, p) == expected
