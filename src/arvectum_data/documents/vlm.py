from __future__ import annotations

import base64
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..models import ModelLocality, VisionRequest, VisionProvider
from .ocr import OCRDocumentResult

_PDFTOPPM = Path("/opt/homebrew/bin/pdftoppm")


@dataclass(frozen=True, slots=True)
class VLMEscalation:
    page_number: int
    reason: str
    text: str
    provider: str
    model: str
    locality: ModelLocality


def pages_requiring_vlm(
    ocr: OCRDocumentResult | None,
    *,
    min_ocr_confidence: float = 90.0,
    min_ocr_chars: int = 24,
) -> tuple[tuple[int, str], ...]:
    if ocr is None:
        return ()
    escalations: list[tuple[int, str]] = []
    for page in ocr.pages:
        if len("".join(page.text.split())) < min_ocr_chars:
            escalations.append((page.page_number, "ocr-low-text"))
        elif page.confidence is not None and page.confidence < min_ocr_confidence:
            escalations.append((page.page_number, "ocr-low-confidence"))
    return tuple(escalations)


def escalate_pdf_pages_to_vlm(
    content: bytes,
    *,
    pages: tuple[tuple[int, str], ...],
    provider: VisionProvider,
    dpi: int = 180,
    timeout_seconds: float = 45,
) -> tuple[VLMEscalation, ...]:
    if not pages:
        return ()
    results: list[VLMEscalation] = []
    with tempfile.TemporaryDirectory(prefix="arvectum-vlm-") as workdir:
        pdf_path = Path(workdir) / "source.pdf"
        pdf_path.write_bytes(content)
        for page_number, reason in pages:
            prefix = Path(workdir) / f"page-{page_number}"
            completed = subprocess.run(
                [
                    str(_PDFTOPPM),
                    "-f",
                    str(page_number),
                    "-singlefile",
                    "-r",
                    str(dpi),
                    "-jpeg",
                    str(pdf_path),
                    str(prefix),
                ],
                capture_output=True,
                check=False,
                timeout=timeout_seconds,
            )
            image_path = prefix.with_suffix(".jpg")
            if completed.returncode != 0 or not image_path.is_file():
                continue
            image_url = "data:image/jpeg;base64," + base64.b64encode(image_path.read_bytes()).decode("ascii")
            response = provider.analyze(
                VisionRequest(
                    prompt=(
                        "Extract the document page faithfully. Preserve table/form structure "
                        "using Markdown tables or labeled fields where structure is visible. "
                        "Do not infer values that are not present."
                    ),
                    image_url=image_url,
                    temperature=0.0,
                )
            )
            results.append(
                VLMEscalation(
                    page_number=page_number,
                    reason=reason,
                    text=response.text,
                    provider=response.provider,
                    model=response.model,
                    locality=response.locality,
                )
            )
    return tuple(results)
