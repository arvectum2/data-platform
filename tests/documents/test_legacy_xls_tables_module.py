"""Bounded original BIFF column order, cell semantics, and fail-closed regressions."""

from types import SimpleNamespace

import xlrd

from arvectum_data.documents import extractor
from arvectum_data.documents.legacy_xls_tables import (
    _extract_xls,
    _format_xls_cell,
)


def _cell(value, ctype=xlrd.XL_CELL_TEXT):
    return SimpleNamespace(value=value, ctype=ctype)


def test_old_extractor_facade_remains_exactly_identical():
    assert extractor._extract_xls is _extract_xls
    assert extractor._format_xls_cell is _format_xls_cell


def test_russian_dates_boolean_prices_and_newlines():
    def cell(value, ctype):
        return _format_xls_cell(_cell(value, ctype), datemode=0, xlrd_module=xlrd)
    assert cell(45292, xlrd.XL_CELL_DATE) == "2024-01-01"
    assert cell(15000, xlrd.XL_CELL_NUMBER) == "15000"
    assert cell(1.25, xlrd.XL_CELL_NUMBER) == "1.25"
    assert cell(1, xlrd.XL_CELL_BOOLEAN) == "TRUE"
    assert cell(0, xlrd.XL_CELL_BOOLEAN) == "FALSE"
    assert cell("Техническое\nзадание", xlrd.XL_CELL_TEXT) == "Техническое задание"
    assert cell(None, xlrd.XL_CELL_EMPTY) == ""


def test_legacy_xls_tabular_russian_source_order_and_blank_columns(monkeypatch):
    rows = [
        [_cell("№"), _cell("Наименование"), _cell("Цена, ₽"), _cell("")],
        [_cell(1, xlrd.XL_CELL_NUMBER), _cell("Монитор 27"), _cell(15000, xlrd.XL_CELL_NUMBER), _cell("")],
        [_cell(2, xlrd.XL_CELL_NUMBER), _cell("Сервер"), _cell(""), _cell("")],
        [_cell(""), _cell(""), _cell(""), _cell("")],
    ]
    class FakeSheet:
        name = "Закупка 2026"
        nrows = len(rows)
        ncols = 4
        def cell(self, i, j):
            return rows[i][j]
    class FakeBook:
        datemode = 0
        def __init__(self):
            self.released = False
        def sheets(self):
            return [FakeSheet()]
        def release_resources(self):
            self.released = True
    book = FakeBook()
    monkeypatch.setattr(xlrd, "open_workbook", lambda **kwargs: book)
    result = _extract_xls(b"ORIGINAL-BIFF")
    assert result.splitlines() == [
        "=== Закупка 2026 ===",
        "№\tНаименование\tЦена, ₽",
        "1\tМонитор 27\t15000",
        "2\tСервер",
    ]
    assert book.released is True


def test_invalid_excel_binary_returns_empty_text_without_fabricating_cells(monkeypatch):
    def error(**kwargs):
        raise ValueError("invalid XLS workbook")
    monkeypatch.setattr(xlrd, "open_workbook", error)
    assert _extract_xls(b"not actual Excel") == ""


def test_empty_workbook_does_not_fabricate_an_evidence_row(monkeypatch):
    workbook = SimpleNamespace(datemode=0, sheets=lambda: [], release_resources=lambda: None)
    monkeypatch.setattr(xlrd, "open_workbook", lambda **kwargs: workbook)
    assert _extract_xls(b"empty-book") == ""
