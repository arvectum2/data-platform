from __future__ import annotations

import io
from dataclasses import dataclass

from ..models import VisionProvider
from .ocr import OCRDocumentResult, OCRProvider
from .vlm import VLMEscalation, escalate_pdf_pages_to_vlm, pages_requiring_vlm


@dataclass(frozen=True, slots=True)
class PDFPageAssessment:
    page_number: int
    native_text: str
    native_char_count: int
    needs_ocr: bool


@dataclass(frozen=True, slots=True)
class PDFExtractionResult:
    text: str
    pages: tuple[PDFPageAssessment, ...]
    ocr: OCRDocumentResult | None = None
    vlm: tuple[VLMEscalation, ...] = ()
    requested_ocr_page_numbers: tuple[int, ...] = ()
    skipped_ocr_page_numbers: tuple[int, ...] = ()
    unresolved_page_numbers: tuple[int, ...] = ()
    text_truncated: bool = False

    @property
    def ocr_page_numbers(self) -> tuple[int, ...]:
        """Pages admitted to the bounded OCR budget, not every PDF page."""
        return self.requested_ocr_page_numbers


def _read_pdf(content: bytes):
    import pypdf

    return pypdf.PdfReader(io.BytesIO(content))


def assess_pdf_pages(
    content: bytes,
    *,
    max_pages: int | None = 10,
    min_native_chars: int = 32,
) -> tuple[PDFPageAssessment, ...]:
    if max_pages is not None and max_pages < 0:
        raise ValueError("max_pages must be non-negative or None")
    try:
        reader = _read_pdf(content)
        pages = []
        for index, page in enumerate(reader.pages, start=1):
            if max_pages is not None and index > max_pages:
                break
            try:
                native_text = (page.extract_text() or "").strip()
            except Exception:
                # A damaged page must not silently erase the rest of the document.
                native_text = ""
            normalized_count = len("".join(native_text.split()))
            pages.append(
                PDFPageAssessment(
                    page_number=index,
                    native_text=native_text,
                    native_char_count=normalized_count,
                    needs_ocr=normalized_count < min_native_chars,
                )
            )
        return tuple(pages)
    except Exception:
        return ()


def extract_pdf_cascade(
    content: bytes,
    *,
    max_chars: int,
    ocr_provider: OCRProvider | None = None,
    vision_provider: VisionProvider | None = None,
    max_pages: int = 10,
    min_native_chars: int = 32,
    min_ocr_confidence: float = 90.0,
    min_ocr_chars: int = 24,
) -> PDFExtractionResult:
    if max_pages < 0:
        raise ValueError("max_pages must be non-negative")
    # Never discard native text after the OCR budget. Most procurement PDFs
    # have more than ten pages, and later pages often contain crucial clauses.
    pages = assess_pdf_pages(content, max_pages=None, min_native_chars=min_native_chars)
    if not pages:
        return PDFExtractionResult("", ())

    ocr: OCRDocumentResult | None = None
    needs_ocr = tuple(page.page_number for page in pages if page.needs_ocr)
    ocr_pages = needs_ocr[:max_pages]
    skipped_ocr_pages = needs_ocr[max_pages:]
    if ocr_provider is not None and ocr_pages:
        ocr = ocr_provider.extract_pdf(content, page_numbers=ocr_pages)
    ocr_by_page = {page.page_number: page for page in (ocr.pages if ocr else ())}
    vlm: tuple[VLMEscalation, ...] = ()
    if vision_provider is not None:
        vlm = escalate_pdf_pages_to_vlm(
            content,
            pages=pages_requiring_vlm(
                ocr,
                min_ocr_confidence=min_ocr_confidence,
                min_ocr_chars=min_ocr_chars,
            ),
            provider=vision_provider,
        )
    vlm_by_page = {page.page_number: page for page in vlm}

    page_texts: list[str] = []
    unresolved: list[int] = []
    for page in pages:
        ocr_replacement = ocr_by_page.get(page.page_number)
        vlm_replacement = vlm_by_page.get(page.page_number)
        if vlm_replacement is not None and vlm_replacement.text.strip():
            selected = vlm_replacement.text
        elif page.needs_ocr and ocr_replacement is not None and ocr_replacement.text.strip():
            selected = ocr_replacement.text
        else:
            selected = page.native_text
            if page.needs_ocr:
                unresolved.append(page.page_number)
        if selected.strip():
            page_texts.append(f"[Page {page.page_number}]\n{selected.strip()}")

    combined = "\n\n".join(page_texts)
    return PDFExtractionResult(
        text=combined[:max_chars],
        pages=pages,
        ocr=ocr,
        vlm=vlm,
        requested_ocr_page_numbers=ocr_pages,
        skipped_ocr_page_numbers=skipped_ocr_pages,
        unresolved_page_numbers=tuple(unresolved),
        text_truncated=len(combined) > max_chars,
    )
