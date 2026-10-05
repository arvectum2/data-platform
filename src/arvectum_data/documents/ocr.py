from __future__ import annotations

import csv
import io
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

_PDFTOPPM = Path("/opt/homebrew/bin/pdftoppm")
_TESSERACT = Path("/opt/homebrew/bin/tesseract")


@dataclass(frozen=True, slots=True)
class TextRegion:
    text: str
    confidence: float | None
    left: int | None = None
    top: int | None = None
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True, slots=True)
class OCRPageResult:
    page_number: int
    text: str
    confidence: float | None
    regions: tuple[TextRegion, ...] = ()
    provider: str = ""
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OCRDocumentResult:
    pages: tuple[OCRPageResult, ...]
    provider: str

    @property
    def text(self) -> str:
        return "\n\n".join(page.text for page in self.pages if page.text.strip())

    @property
    def mean_confidence(self) -> float | None:
        values = [page.confidence for page in self.pages if page.confidence is not None]
        return round(sum(values) / len(values), 2) if values else None


@runtime_checkable
class OCRProvider(Protocol):
    provider_name: str

    def extract_pdf(self, content: bytes, *, page_numbers: tuple[int, ...]) -> OCRDocumentResult: ...


class TesseractOCRProvider:
    provider_name = "tesseract"

    def __init__(
        self,
        *,
        languages: str = "rus+eng",
        dpi: int = 220,
        timeout_seconds: float = 45,
        pdftoppm_path: Path = _PDFTOPPM,
        tesseract_path: Path = _TESSERACT,
    ) -> None:
        self.languages = languages
        self.dpi = dpi
        self.timeout_seconds = timeout_seconds
        self.pdftoppm_path = pdftoppm_path
        self.tesseract_path = tesseract_path

    def extract_pdf(self, content: bytes, *, page_numbers: tuple[int, ...]) -> OCRDocumentResult:
        if not page_numbers:
            return OCRDocumentResult((), self.provider_name)
        if not self.pdftoppm_path.is_file() or not self.tesseract_path.is_file():
            raise RuntimeError("local OCR runtime is unavailable")

        pages: list[OCRPageResult] = []
        with tempfile.TemporaryDirectory(prefix="arvectum-ocr-") as workdir:
            pdf_path = Path(workdir) / "source.pdf"
            pdf_path.write_bytes(content)
            for page_number in page_numbers:
                png_prefix = Path(workdir) / f"page-{page_number}"
                render = subprocess.run(
                    [
                        str(self.pdftoppm_path),
                        "-f",
                        str(page_number),
                        "-singlefile",
                        "-r",
                        str(self.dpi),
                        "-png",
                        str(pdf_path),
                        str(png_prefix),
                    ],
                    capture_output=True,
                    check=False,
                    timeout=self.timeout_seconds,
                )
                png_path = png_prefix.with_suffix(".png")
                if render.returncode != 0 or not png_path.is_file():
                    pages.append(
                        OCRPageResult(
                            page_number=page_number,
                            text="",
                            confidence=None,
                            provider=self.provider_name,
                            metadata={"status": "render-failed"},
                        )
                    )
                    continue
                pages.append(self._ocr_image(png_path, page_number))
        return OCRDocumentResult(tuple(pages), self.provider_name)

    def _ocr_image(self, image_path: Path, page_number: int) -> OCRPageResult:
        completed = subprocess.run(
            [
                str(self.tesseract_path),
                image_path.name,
                "stdout",
                "-l",
                self.languages,
                "--psm",
                "6",
                "tsv",
            ],
            capture_output=True,
            check=False,
            timeout=self.timeout_seconds,
            cwd=image_path.parent,
        )
        if completed.returncode != 0:
            return OCRPageResult(
                page_number=page_number,
                text="",
                confidence=None,
                provider=self.provider_name,
                metadata={"status": "ocr-failed"},
            )

        regions: list[TextRegion] = []
        rows = csv.DictReader(io.StringIO(completed.stdout.decode("utf-8", errors="replace")), delimiter="\t")
        for row in rows:
            text = (row.get("text") or "").strip()
            if not text:
                continue
            try:
                confidence = float(row.get("conf", "-1"))
            except ValueError:
                confidence = -1
            if confidence < 0:
                continue
            try:
                box = tuple(int(row.get(key, "0")) for key in ("left", "top", "width", "height"))
            except ValueError:
                box = (None, None, None, None)
            regions.append(TextRegion(text, confidence, *box))

        text = " ".join(region.text for region in regions)
        confidence = (
            round(sum(region.confidence or 0 for region in regions) / len(regions), 2)
            if regions
            else None
        )
        return OCRPageResult(
            page_number=page_number,
            text=text,
            confidence=confidence,
            regions=tuple(regions),
            provider=self.provider_name,
            metadata={"status": "ok", "languages": self.languages, "dpi": self.dpi},
        )
