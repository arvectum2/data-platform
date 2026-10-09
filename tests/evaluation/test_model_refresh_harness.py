from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from benchmark_embedding_refresh import HtmlText, cosine, site_corpus  # noqa: E402
from benchmark_ocr_refresh import distance, normalize, score  # noqa: E402


def test_russian_text_corpus_uses_main_not_hidden_scripts(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(
        '<html><head><title>Закупки</title><meta name="description" '
        'content="Поиск поставщика"></head>'
        '<body><script>НЕЛЕГАЛЬНЫЙ_ТЕКСТ</script>'
        '<main><h1>Контракт</h1><p>Сумма НМЦК</p>'
        '<script>НЕЛЕГАЛЬНЫЙ_ТЕКСТ</script>'
        '<p>Поставка товаров</p></main></body></html>',
        encoding="utf-8",
    )
    results = site_corpus(tmp_path)
    assert len(results) == 1
    assert results[0]["uri"] == "https://arvectum.com/"
    assert "Контракт" in results[0]["text"]
    assert "НЕЛЕГАЛЬНЫЙ_ТЕКСТ" not in results[0]["text"]
    assert "Поиск поставщика" in results[0]["text"]


def test_embedding_cosine_similarity_rejects_zero_vector() -> None:
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine([0.0, 0.0], [1.0, 0.0]) == -1


def test_ocr_edit_distance_and_required_fields() -> None:
    assert distance("контракт", "контракт") == 0
    assert distance("контракт", "контркт") == 1
    result = score("Контракт № 123", "Контракт № 123", ["Контракт", "123"])
    assert result["cer"] == 0
    assert result["wer"] == 0
    assert result["required_text_passed"]
    assert not score("Тест", "Текст", ["Тест"])["required_text_passed"]


def test_ocr_page_marker_normalization() -> None:
    assert normalize("[Page 1]  Срок \u00a0 исполнения") == "Срок исполнения"
