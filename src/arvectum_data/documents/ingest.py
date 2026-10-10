from __future__ import annotations

import hashlib
import mimetypes
import re
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from ..acquisition import AcquisitionEngine, AcquisitionRequest
from ..core import Chunk, Document, Provenance, Resource
from ..models import VisionProvider
from ..processing.chunking import ChunkingConfig, chunk_text
from .extractor import extract_text
from .ocr import OCRProvider
from .pdf_pipeline import extract_pdf_cascade


@dataclass(frozen=True, slots=True)
class DocumentIngestResult:
    resource: Resource
    document: Document
    chunks: tuple[Chunk, ...]


def _stable_id(*parts: str) -> str:
    payload = "\0".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _html_to_text(html: str) -> str:
    clean = re.sub(
        r"<script[^>]*>.*?</script>",
        "",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    clean = re.sub(
        r"<style[^>]*>.*?</style>",
        "",
        clean,
        flags=re.DOTALL | re.IGNORECASE,
    )
    clean = re.sub(r"<[^>]+>", " ", clean)
    return re.sub(r"\s+", " ", clean).strip()


def _build_result(
    *,
    collection_id: str,
    source_type: str,
    canonical_uri: str,
    title: str,
    media_type: str,
    text: str,
    extraction_status: str,
    content_hash: str,
    metadata: dict,
    chunking: ChunkingConfig | None,
) -> DocumentIngestResult:
    resource_id = _stable_id("resource", collection_id, source_type, canonical_uri)
    document_id = _stable_id("document", resource_id, content_hash)

    resource = Resource(
        resource_id=resource_id,
        collection_id=collection_id,
        source_type=source_type,
        canonical_uri=canonical_uri,
        content_hash=content_hash,
        metadata=metadata,
    )
    document = Document(
        document_id=document_id,
        resource_id=resource_id,
        title=title,
        text=text,
        content_hash=content_hash,
        media_type=media_type,
        extraction_status=extraction_status,
        metadata=metadata,
    )
    provenance = Provenance(
        resource_id=resource_id,
        document_id=document_id,
        canonical_uri=canonical_uri,
        content_hash=content_hash,
    )
    drafts = chunk_text(text, chunking or ChunkingConfig())
    chunks = tuple(
        Chunk(
            chunk_id=_stable_id("chunk", document_id, draft.text_hash, str(draft.chunk_index)),
            document_id=document_id,
            ordinal=draft.chunk_index,
            text=draft.text,
            content_hash=draft.text_hash,
            char_start=draft.char_start,
            char_end=draft.char_end,
            token_estimate=draft.token_estimate,
            provenance=provenance,
            metadata=metadata,
        )
        for draft in drafts
    )
    return DocumentIngestResult(resource=resource, document=document, chunks=chunks)


def ingest_file(
    path: str | Path,
    *,
    collection_id: str,
    source_type: str = "file",
    canonical_uri: str | None = None,
    title: str | None = None,
    chunking: ChunkingConfig | None = None,
    pre_chunked: bool = False,
    max_chars: int = 2_000_000,
    ocr_provider: OCRProvider | None = None,
    vision_provider: VisionProvider | None = None,
) -> DocumentIngestResult:
    if not collection_id.strip():
        raise ValueError("collection_id must not be blank")

    file_path = Path(path).expanduser().resolve()
    content = file_path.read_bytes()
    content_hash = hashlib.sha256(content).hexdigest()
    uri = canonical_uri or file_path.as_uri()
    media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    metadata = {"file_name": file_path.name}
    if content.startswith(b"%PDF-"):
        pdf_result = extract_pdf_cascade(
            content,
            max_chars=max_chars,
            ocr_provider=ocr_provider,
            vision_provider=vision_provider,
        )
        text = pdf_result.text
        status = "extracted" if text.strip() else "empty"
        metadata["pdf_pages"] = [
            {
                "page_number": page.page_number,
                "native_char_count": page.native_char_count,
                "needs_ocr": page.needs_ocr,
            }
            for page in pdf_result.pages
        ]
        metadata["pdf_page_count"] = len(pdf_result.pages)
        metadata["text_truncated"] = pdf_result.text_truncated
        metadata["ocr"] = {
            "provider": pdf_result.ocr.provider if pdf_result.ocr else None,
            "page_numbers": list(pdf_result.ocr_page_numbers),
            "skipped_page_numbers": list(pdf_result.skipped_ocr_page_numbers),
            "unresolved_page_numbers": list(pdf_result.unresolved_page_numbers),
            "mean_confidence": (
                pdf_result.ocr.mean_confidence if pdf_result.ocr else None
            ),
            "pages": [
                {
                    "page_number": page.page_number,
                    "confidence": page.confidence,
                    "regions": [
                        {
                            "text": region.text,
                            "confidence": region.confidence,
                            "left": region.left,
                            "top": region.top,
                            "width": region.width,
                            "height": region.height,
                        }
                        for region in page.regions
                    ],
                }
                for page in (pdf_result.ocr.pages if pdf_result.ocr else ())
            ],
        }
        if pdf_result.unresolved_page_numbers:
            metadata["extraction_warnings"] = [
                "native text insufficient and OCR/VLM text unavailable on pages: "
                + ", ".join(str(page) for page in pdf_result.unresolved_page_numbers)
            ]
        metadata["vlm"] = [
            {
                "page_number": page.page_number,
                "reason": page.reason,
                "provider": page.provider,
                "model": page.model,
                "locality": page.locality.value,
            }
            for page in pdf_result.vlm
        ]
    else:
        status, text = extract_text(str(file_path), max_chars=max_chars)
    resolved_chunking = chunking
    if pre_chunked:
        resolved_chunking = ChunkingConfig(
            chunk_size_chars=max(1, len(text)),
            overlap_chars=0,
            min_chunk_chars=1,
        )
        metadata["pre_chunked"] = True

    return _build_result(
        collection_id=collection_id,
        source_type=source_type,
        canonical_uri=uri,
        title=title or file_path.name,
        media_type=media_type,
        text=text,
        extraction_status=status,
        content_hash=content_hash,
        metadata=metadata,
        chunking=resolved_chunking,
    )


def ingest_bytes(
    content: bytes,
    *,
    filename: str,
    collection_id: str,
    source_type: str = "file",
    canonical_uri: str | None = None,
    title: str | None = None,
    chunking: ChunkingConfig | None = None,
    pre_chunked: bool = False,
    max_chars: int = 2_000_000,
    ocr_provider: OCRProvider | None = None,
    vision_provider: VisionProvider | None = None,
) -> DocumentIngestResult:
    """Ingest uploaded bytes through the same format-aware pipeline as local files.

    Legacy Office converters require a path, so a short-lived private directory
    is used for *all* formats. Its random path must not escape into source
    metadata, IDs or provenance; uploads retain their original logical name.
    """
    safe_suffix = Path(filename).suffix[:16]
    with tempfile.TemporaryDirectory(prefix="arvectum-upload-") as workdir:
        temporary = Path(workdir) / f"source{safe_suffix}"
        temporary.write_bytes(content)
        result = ingest_file(
            temporary,
            collection_id=collection_id,
            source_type=source_type,
            canonical_uri=canonical_uri or f"upload://{filename}",
            title=title or filename,
            chunking=chunking,
            pre_chunked=pre_chunked,
            max_chars=max_chars,
            ocr_provider=ocr_provider,
            vision_provider=vision_provider,
        )
    # All projections must agree on original source metadata. Never mutate the
    # mappings shared by the frozen models returned from ingest_file().
    metadata = {**result.document.metadata, "file_name": filename}
    return replace(
        result,
        resource=replace(result.resource, metadata=metadata),
        document=replace(result.document, metadata=metadata),
        chunks=tuple(replace(chunk, metadata=metadata) for chunk in result.chunks),
    )


def ingest_url(
    url: str,
    *,
    collection_id: str,
    acquisition: AcquisitionEngine | None = None,
    title: str | None = None,
    chunking: ChunkingConfig | None = None,
    timeout_s: float = 20.0,
    max_bytes: int = 5_000_000,
) -> DocumentIngestResult:
    if not collection_id.strip():
        raise ValueError("collection_id must not be blank")

    acquired = (acquisition or AcquisitionEngine()).acquire(
        AcquisitionRequest(
            url=url,
            timeout_s=timeout_s,
            max_bytes=max_bytes,
        )
    )
    asset = acquired.asset
    canonical_uri = asset.source_url or url
    if asset.html is not None:
        source_text = asset.html
        text = _html_to_text(asset.html)
        media_type = "text/html"
    else:
        source_text = asset.text or ""
        text = source_text
        media_type = "text/plain"

    content_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    acquisition_meta = asset.metadata.get("acquisition", {})
    metadata = {
        "requested_url": url,
        "acquisition_method": acquisition_meta.get("method"),
        "rendered": bool(acquisition_meta.get("rendered", False)),
        "etag": acquisition_meta.get("etag"),
        "last_modified": acquisition_meta.get("last_modified"),
        "warnings": tuple(acquired.warnings),
    }

    return _build_result(
        collection_id=collection_id,
        source_type="url",
        canonical_uri=canonical_uri,
        title=title or canonical_uri,
        media_type=media_type,
        text=text,
        extraction_status="extracted" if text.strip() else "empty",
        content_hash=content_hash,
        metadata=metadata,
        chunking=chunking,
    )
