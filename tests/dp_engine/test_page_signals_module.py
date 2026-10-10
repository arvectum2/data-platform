"""The classifier retains its facade and parser safety constraints."""

from arvectum_data.crawl import relevance
from arvectum_data.crawl.page_signals import _PageSignals, _SignalHTMLParser


def test_classifier_facade_reuses_standalone_parser():
    assert relevance._PageSignals is _PageSignals
    assert relevance._SignalHTMLParser is _SignalHTMLParser


def test_ignores_script_and_preserves_russian_title_description():
    parser = _SignalHTMLParser()
    parser.feed(
        '<html><head><title>Скидки на технику</title>'
        '<meta name="description" content="Акция сегодня"></head>'
        '<body><h1>Магазин</h1><script>fake promo</script>'
        '<p>Настоящий купон</p></body></html>'
    )
    actual = parser.signals()
    assert actual.title == "Скидки на технику"
    assert actual.h1 == "Магазин"
    assert actual.meta_description == "Акция сегодня"
    assert "fake promo" not in actual.visible_text
    assert "Настоящий купон" in actual.visible_text


def test_parser_bound_excludes_excess_visible_prose():
    parser = _SignalHTMLParser(max_visible_chars=5)
    parser.feed("<div>ABCDEFGHIJKL</div>")
    assert parser.signals().visible_text == "ABCDE"
