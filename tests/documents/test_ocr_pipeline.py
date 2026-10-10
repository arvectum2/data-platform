from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter

from arvectum_data.documents import (
    OCRDocumentResult,
    OCRPageResult,
    TextRegion,
    extract_pdf_cascade,
    ingest_file,
)


class FakeOCR:
    provider_name = "fake-ocr"

    def __init__(self):
        self.requested = ()

    def extract_pdf(self, content: bytes, *, page_numbers: tuple[int, ...]):
        self.requested = page_numbers
        return OCRDocumentResult(
            pages=tuple(
                OCRPageResult(
                    page_number=page,
                    text=f"OCR page {page}",
                    confidence=91.5,
                    regions=(TextRegion("OCR", 91.5, 10, 20, 30, 40),),
                    provider=self.provider_name,
                )
                for page in page_numbers
            ),
            provider=self.provider_name,
        )


def _write_blank_pdf(path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with path.open("wb") as handle:
        writer.write(handle)


def test_page_with_native_text_does_not_escalate_to_ocr(monkeypatch):
    from arvectum_data.documents import pdf_pipeline

    class Page:
        def extract_text(self):
            return "Native procurement text " * 5

    class Reader:
        pages = [Page()]

    monkeypatch.setattr(pdf_pipeline, "_read_pdf", lambda content: Reader())
    provider = FakeOCR()

    result = extract_pdf_cascade(b"%PDF-fake", max_chars=10000, ocr_provider=provider)

    assert result.pages[0].needs_ocr is False
    assert provider.requested == ()
    assert "Native procurement text" in result.text


def test_image_only_page_escalates_to_ocr(tmp_path: Path):
    path = tmp_path / "scan.pdf"
    _write_blank_pdf(path)
    provider = FakeOCR()

    result = extract_pdf_cascade(path.read_bytes(), max_chars=10000, ocr_provider=provider)

    assert result.ocr_page_numbers == (1,)
    assert provider.requested == (1,)
    assert "[Page 1]" in result.text
    assert "OCR page 1" in result.text
    assert result.ocr.mean_confidence == 91.5


def test_ingest_preserves_ocr_provenance_and_coordinates(tmp_path: Path):
    path = tmp_path / "scan.pdf"
    _write_blank_pdf(path)

    result = ingest_file(path, collection_id="tests:ocr", ocr_provider=FakeOCR())

    assert result.document.extraction_status == "extracted"
    assert result.document.metadata["ocr"]["provider"] == "fake-ocr"
    assert result.document.metadata["ocr"]["page_numbers"] == [1]
    region = result.document.metadata["ocr"]["pages"][0]["regions"][0]
    assert region["left"] == 10
    assert region["top"] == 20
    assert region["confidence"] == 91.5


def test_vlm_escalation_selector_is_bounded_to_bad_ocr():
    from arvectum_data.documents import pages_requiring_vlm

    ocr = OCRDocumentResult(
        pages=(
            OCRPageResult(1, "good text " * 10, 92.0, provider="fake"),
            OCRPageResult(2, "x", 95.0, provider="fake"),
            OCRPageResult(3, "enough text " * 10, 55.0, provider="fake"),
        ),
        provider="fake",
    )

    assert pages_requiring_vlm(ocr) == (
        (2, "ocr-low-text"),
        (3, "ocr-low-confidence"),
    )

def test_vlm_default_confidence_gate_matches_real_scan_profiles():
    from arvectum_data.documents import pages_requiring_vlm

    ocr = OCRDocumentResult(
        pages=(
            OCRPageResult(1, "x" * 1148, 86.89, provider="recorded-tesseract"),
            OCRPageResult(2, "x" * 2221, 94.41, provider="recorded-tesseract"),
        ),
        provider="recorded-tesseract",
    )

    assert pages_requiring_vlm(ocr) == ((1, "ocr-low-confidence"),)


def test_long_native_pdf_preserves_pages_beyond_bounded_ocr_budget(monkeypatch):
    from arvectum_data.documents import pdf_pipeline

    class Page:
        def __init__(self, number):
            self.number = number

        def extract_text(self):
            return f"Страница {self.number}: " + "Технические условия поставки. " * 6

    class Reader:
        pages = [Page(n) for n in range(1, 14)]

    monkeypatch.setattr(pdf_pipeline, "_read_pdf", lambda content: Reader())
    result = extract_pdf_cascade(b"pdf", max_chars=50000, ocr_provider=FakeOCR())
    assert len(result.pages) == 13
    assert "[Page 13]" in result.text
    assert "Страница 13" in result.text
    assert result.ocr_page_numbers == ()
    assert result.text_truncated is False


def test_long_scanned_pdf_exposes_ocr_budget_and_incomplete_pages(tmp_path: Path):
    source = tmp_path / "long-scan.pdf"
    writer = PdfWriter()
    for _ in range(12):
        writer.add_blank_page(width=595, height=842)
    with source.open("wb") as handle:
        writer.write(handle)

    provider = FakeOCR()
    result = ingest_file(source, collection_id="tenant:long-scan", ocr_provider=provider)

    assert provider.requested == tuple(range(1, 11))
    assert result.document.metadata["pdf_page_count"] == 12
    assert result.document.metadata["ocr"]["page_numbers"] == list(range(1, 11))
    assert result.document.metadata["ocr"]["skipped_page_numbers"] == [11, 12]
    assert result.document.metadata["ocr"]["unresolved_page_numbers"] == [11, 12]
    assert "[Page 10]" in result.document.text
    assert "[Page 11]" not in result.document.text
    assert "extraction_warnings" in result.document.metadata


def test_pdf_extraction_reports_character_budget_truncation(monkeypatch):
    from arvectum_data.documents import pdf_pipeline

    class Page:
        def extract_text(self):
            return "Длинный документ " * 80

    class Reader:
        pages = [Page()]

    monkeypatch.setattr(pdf_pipeline, "_read_pdf", lambda content: Reader())
    result = extract_pdf_cascade(b"pdf", max_chars=60)
    assert len(result.text) == 60
    assert result.text_truncated is True
