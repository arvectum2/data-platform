from __future__ import annotations

import hashlib
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path

from ..acquisition import AcquisitionEngine, AcquisitionRequest
from ..core import Chunk, Document, Provenance, Resource
from ..processing.chunking import ChunkingConfig, chunk_text
from .extractor import extract_text


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
    max_chars: int = 2_000_000,
) -> DocumentIngestResult:
    if not collection_id.strip():
        raise ValueError("collection_id must not be blank")

    file_path = Path(path).expanduser().resolve()
    content = file_path.read_bytes()
    content_hash = hashlib.sha256(content).hexdigest()
    uri = canonical_uri or file_path.as_uri()
    status, text = extract_text(str(file_path), max_chars=max_chars)
    media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    metadata = {"file_name": file_path.name}

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
        chunking=chunking,
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
