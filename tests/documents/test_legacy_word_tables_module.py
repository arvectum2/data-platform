"""Public extraction facade and isolated wvHtml projection use one implementation."""

from arvectum_data.documents import extractor
from arvectum_data.documents.legacy_word_tables import (
    _WvHtmlTableProjector,
    _project_wvhtml_tables,
)


def test_facade_shares_single_table_implementation():
    assert extractor._project_wvhtml_tables is _project_wvhtml_tables
    assert extractor._WvHtmlTableProjector is _WvHtmlTableProjector


def test_legacy_word_table_preserves_separate_same_name_rows_and_inline_markup():
    html = (
        "<p>Расчет НМЦК</p><table>"
        "<tr><th>Наименование</th><th>Количество</th></tr>"
        "<tr><td>Товар <b>А</b></td><td>1</td></tr>"
        "<tr><td>Товар <b>А</b></td><td>2</td></tr>"
        "</table><script>hidden()</script><p>Итого</p>"
    ).encode()
    result = _project_wvhtml_tables(html, 1000)
    assert result.splitlines() == [
        "Расчет НМЦК",
        "Наименование\tКоличество",
        "Товар А\t1",
        "Товар А\t2",
        "Итого",
    ]


def test_legacy_word_table_rejects_prose_only_and_caps_result():
    assert _project_wvhtml_tables(b"<p>no table</p>", 100) == ""
    assert _project_wvhtml_tables(b"<tr><td>1</td></tr>", 100) == ""
    assert _project_wvhtml_tables(b"<table><tr><td>1</td><td>2</td></tr></table>", 3) == "1\t2"
