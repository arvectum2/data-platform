"""Check independently obtained attachment bytes against stored DP identity.

This is a *storage integrity* check. A caller must independently establish
that supplied bytes and notice revision belong to the authoritative EIS record.
Comparing two values stored inside DP cannot itself prove EIS authenticity.
The checker is pure: no network, disk I/O, uploads, or source content logging.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any, Mapping


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OriginalBinaryAudit:
    binary_matches_store: bool
    notice_revision_metadata_matches: bool
    checked_documents: int
    error_codes: tuple[str, ...]

    @property
    def ready_for_authoritative_source_review(self) -> bool:
        """Still requires independent source retrieval/revision attestation."""
        return self.binary_matches_store and self.notice_revision_metadata_matches


def audit_original_attachment(
    original_bytes: bytes,
    exported_resource: Mapping[str, Any],
    *,
    expected_collection_id: str,
    expected_source_type: str,
    expected_canonical_uri: str,
    expected_notice_revision: str | None = None,
) -> OriginalBinaryAudit:
    """Compare original bytes to DP's resource/document content hashes and IDs.

    The expected URI, collection and optional notice revision MUST come from
    independent authority, not copied from the DP export under examination.
    Never use this result alone as proof the source is authentic EIS material.
    """
    errors: set[str] = set()
    if not isinstance(original_bytes, bytes) or not original_bytes:
        return OriginalBinaryAudit(False, False, 0, ("MISSING_ORIGINAL_BYTES",))
    if not all(
        isinstance(value, str) and value.strip()
        for value in (expected_collection_id, expected_source_type, expected_canonical_uri)
    ):
        return OriginalBinaryAudit(False, False, 0, ("MISSING_INDEPENDENT_SOURCE_ID",))
    if not isinstance(exported_resource, Mapping):
        return OriginalBinaryAudit(False, False, 0, ("MALFORMED_RESOURCE",))

    canonical_uri = exported_resource.get("canonical_uri")
    if canonical_uri != expected_canonical_uri:
        errors.add("CANONICAL_URI_MISMATCH")
    source_type = exported_resource.get("source_type")
    if source_type != expected_source_type:
        errors.add("SOURCE_TYPE_MISMATCH")

    expected_resource_id = _stable_id(
        "resource", expected_collection_id, expected_source_type, expected_canonical_uri
    )
    resource_id = exported_resource.get("resource_id")
    if not isinstance(resource_id, str) or not hmac.compare_digest(resource_id, expected_resource_id):
        errors.add("RESOURCE_ID_MISMATCH")

    digest = hashlib.sha256(original_bytes).hexdigest()
    resource_hash = exported_resource.get("content_hash")
    if not isinstance(resource_hash, str) or not hmac.compare_digest(
        resource_hash.lower(), digest
    ):
        errors.add("RESOURCE_BINARY_HASH_MISMATCH")

    documents = exported_resource.get("documents")
    if not isinstance(documents, list) or not documents:
        errors.add("NO_DOCUMENTS")
        documents = []
    matching_documents = 0
    for document in documents:
        if not isinstance(document, Mapping):
            errors.add("MALFORMED_DOCUMENT")
            continue
        document_hash = document.get("content_hash")
        expected_document_id = _stable_id("document", expected_resource_id, digest)
        document_id = document.get("document_id")
        if (
            isinstance(document_hash, str)
            and hmac.compare_digest(document_hash.lower(), digest)
            and isinstance(document_id, str)
            and hmac.compare_digest(document_id, expected_document_id)
        ):
            matching_documents += 1
    if matching_documents != 1:
        errors.add("ORIGINAL_DOCUMENT_HASH_OR_ID_MISMATCH")

    stored_metadata = exported_resource.get("metadata")
    revision_match = (
        isinstance(expected_notice_revision, str)
        and bool(expected_notice_revision.strip())
        and isinstance(stored_metadata, Mapping)
        and stored_metadata.get("notice_revision") == expected_notice_revision
    )
    if not revision_match:
        errors.add("NOTICE_REVISION_NOT_INDEPENDENTLY_MATCHED")

    binary_errors = errors - {"NOTICE_REVISION_NOT_INDEPENDENTLY_MATCHED"}
    return OriginalBinaryAudit(
        binary_matches_store=not binary_errors,
        notice_revision_metadata_matches=bool(revision_match),
        checked_documents=len(documents),
        error_codes=tuple(sorted(errors)),
    )
