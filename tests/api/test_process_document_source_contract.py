"""Cross-product source contract: never emit negative/ambiguous chunk locations."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from arvectum_data.api.contract import (
    CONSUMER_CONTRACT_NAME,
    CONSUMER_CONTRACT_VERSION,
)
from arvectum_data.api.schemas import (
    ProcessDocumentResponse,
    ProcessedChunkResponse,
)


def payload():
    return {
        "resource_id": "resource-eis-original-1",
        "document_id": "document-eis-original-1",
        "collection_id": "tender-documents",
        "canonical_uri": "content-sha256://abc",
        "title": "ТЗ.docx",
        "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "extraction_status": "extracted",
        "metadata": {"source_page": 4, "ocr_engine": "validated"},
        "text": "Требование: срок исполнения 45 дней.",
        "chunks": [{
            "chunk_id": "chunk-1",
            "ordinal": 0,
            "text": "Требование: срок исполнения 45 дней.",
            "content_hash": "sha256-1",
            "char_start": 0,
            "char_end": 36,
            "token_estimate": 7,
        }],
    }


def test_v1_contract_preserves_resource_document_chunk_and_source_locations():
    doc = ProcessDocumentResponse.model_validate(payload())
    assert CONSUMER_CONTRACT_NAME == "arvectum-data-consumer"
    assert CONSUMER_CONTRACT_VERSION == "1.0"
    assert doc.resource_id == "resource-eis-original-1"
    assert doc.document_id == "document-eis-original-1"
    assert doc.canonical_uri == "content-sha256://abc"
    assert doc.metadata["source_page"] == 4
    assert doc.chunks[0].chunk_id == "chunk-1"
    assert doc.chunks[0].char_start == 0
    assert doc.chunks[0].char_end == 36


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("chunk_id", ""),
        ("content_hash", ""),
        ("ordinal", -1),
        ("char_start", -1),
        ("char_end", -1),
        ("token_estimate", -1),
    ],
)
def test_invalid_source_coordinate_or_identity_fails_closed(field, value):
    chunk = dict(payload()["chunks"][0])
    chunk[field] = value
    with pytest.raises(ValidationError):
        ProcessedChunkResponse.model_validate(chunk)


def test_backwards_source_span_fails_closed():
    chunk = dict(payload()["chunks"][0])
    chunk["char_start"] = 60
    chunk["char_end"] = 40
    with pytest.raises(ValidationError, match="char_end cannot precede char_start"):
        ProcessedChunkResponse.model_validate(chunk)
