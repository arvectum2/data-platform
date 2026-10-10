"""Validate Data Platform exported text chunks without disclosing source content.

Coordinates refer to normalize_text(document.text), not raw original
file bytes or unnormalized document text. Document hashes may identify raw
source binaries; they are not compared with extracted text by this helper.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any, Mapping

from arvectum_data.processing.chunking import normalize_text


@dataclass(frozen=True)
class ChunkExportAudit:
    resources: int
    documents: int
    chunks: int
    matching_chunk_hashes: int
    matching_normalized_offsets: int
    error_codes: tuple[str, ...]

    @property
    def verified(self) -> bool:
        return (
            self.chunks > 0
            and self.chunks == self.matching_chunk_hashes
            and self.chunks == self.matching_normalized_offsets
            and not self.error_codes
        )


def audit_chunk_export(payload: Mapping[str, Any]) -> ChunkExportAudit:
    """Audit an include_content=true collection export, never EIS original bytes."""
    resource_count = doc_count = chunk_count = hash_ok = offset_ok = 0
    errors: set[str] = set()
    if payload.get("include_content") is not True:
        errors.add("CONTENT_NOT_INCLUDED")
    resources = payload.get("resources")
    if not isinstance(resources, list):
        return ChunkExportAudit(0, 0, 0, 0, 0, ("MALFORMED_RESOURCES",))
    for resource in resources:
        resource_count += 1
        if not isinstance(resource, dict):
            errors.add("MALFORMED_RESOURCE")
            continue
        if not resource.get("resource_id"):
            errors.add("MISSING_RESOURCE_ID")
        documents = resource.get("documents")
        if not isinstance(documents, list):
            errors.add("MALFORMED_DOCUMENTS")
            continue
        for document in documents:
            doc_count += 1
            if not isinstance(document, dict):
                errors.add("MALFORMED_DOCUMENT")
                continue
            if not document.get("document_id"):
                errors.add("MISSING_DOCUMENT_ID")
            original_text = document.get("text")
            normalized = normalize_text(original_text) if isinstance(original_text, str) else None
            if normalized is None:
                errors.add("MISSING_DOCUMENT_TEXT")
            chunks = document.get("chunks")
            if not isinstance(chunks, list):
                errors.add("MALFORMED_CHUNKS")
                continue
            for chunk in chunks:
                chunk_count += 1
                if not isinstance(chunk, dict):
                    errors.add("MALFORMED_CHUNK")
                    continue
                if not chunk.get("chunk_id"):
                    errors.add("MISSING_CHUNK_ID")
                text = chunk.get("text")
                digest = chunk.get("content_hash")
                if isinstance(text, str) and isinstance(digest, str) and hmac.compare_digest(
                    hashlib.sha256(text.encode("utf-8")).hexdigest(), digest.lower()
                ):
                    hash_ok += 1
                else:
                    errors.add("CHUNK_HASH_MISMATCH_OR_MISSING_TEXT")
                start, end = chunk.get("char_start"), chunk.get("char_end")
                if (
                    normalized is not None
                    and isinstance(start, int)
                    and not isinstance(start, bool)
                    and isinstance(end, int)
                    and not isinstance(end, bool)
                    and 0 <= start < end <= len(normalized)
                    and isinstance(text, str)
                    and normalized[start:end].strip() == text
                ):
                    offset_ok += 1
                else:
                    errors.add("NORMALIZED_OFFSET_MISMATCH")
    if not chunk_count:
        errors.add("NO_CHUNKS")
    return ChunkExportAudit(
        resource_count, doc_count, chunk_count, hash_ok, offset_ok, tuple(sorted(errors))
    )
