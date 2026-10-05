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
