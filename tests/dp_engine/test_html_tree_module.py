from arvectum_data.engine import html_records
from arvectum_data.engine.html_tree import _Node, _TreeParser


def test_previous_private_parser_facade_preserved():
    assert html_records._TreeParser is _TreeParser
    assert html_records._Node is _Node


def test_nested_russian_dom_paths_and_text():
    parser = _TreeParser()
    parser.feed("<div><p>Закупка <b>оборудования</b></p><p>Документы</p></div>")
    paragraphs = [n for n in parser.root.walk() if n.tag == "p"]
    assert len(paragraphs) == 2
    assert paragraphs[0].path.endswith("/div[1]/p[1]")
    assert paragraphs[1].path.endswith("/div[1]/p[2]")
    assert paragraphs[0].text() == "Закупка оборудования"


def test_cached_text_invalidated_after_incremental_feed():
    parser = _TreeParser()
    parser.feed("<div>первая")
    assert parser.root.text() == "первая"
    parser.feed(" вторая</div>")
    assert parser.root.text() == "первая вторая"


def test_void_img_does_not_absorb_following_text():
    parser = _TreeParser()
    parser.feed("<div><img src='logo.png'>Описание</div>")
    assert parser.root.text() == "Описание"
