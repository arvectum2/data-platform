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

    @property
    def ocr_page_numbers(self) -> tuple[int, ...]:
        return tuple(page.page_number for page in self.pages if page.needs_ocr)


def _read_pdf(content: bytes):
    import pypdf

    return pypdf.PdfReader(io.BytesIO(content))


def assess_pdf_pages(
    content: bytes,
    *,
    max_pages: int = 10,
    min_native_chars: int = 32,
) -> tuple[PDFPageAssessment, ...]:
    try:
        reader = _read_pdf(content)
        pages = []
        for index, page in enumerate(reader.pages[:max_pages], start=1):
            native_text = (page.extract_text() or "").strip()
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
    pages = assess_pdf_pages(
        content,
        max_pages=max_pages,
        min_native_chars=min_native_chars,
    )
    if not pages:
        return PDFExtractionResult("", ())

    ocr: OCRDocumentResult | None = None
    ocr_pages = tuple(page.page_number for page in pages if page.needs_ocr)
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
    for page in pages:
        ocr_replacement = ocr_by_page.get(page.page_number)
        vlm_replacement = vlm_by_page.get(page.page_number)
        if vlm_replacement is not None and vlm_replacement.text.strip():
            selected = vlm_replacement.text
        elif page.needs_ocr and ocr_replacement is not None and ocr_replacement.text.strip():
            selected = ocr_replacement.text
        else:
            selected = page.native_text
        if selected.strip():
            page_texts.append(f"[Page {page.page_number}]\n{selected.strip()}")

    return PDFExtractionResult("\n\n".join(page_texts)[:max_chars], pages, ocr, vlm)
