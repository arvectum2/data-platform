"""Check provenance of exported chunks in the normalized text coordinate system."""

from __future__ import annotations

import copy
import hashlib

from arvectum_data.processing.chunk_export_audit import audit_chunk_export
from arvectum_data.processing.chunking import ChunkingConfig, chunk_text


def _export(original: str) -> dict:
    parts = chunk_text(
        original, ChunkingConfig(chunk_size_chars=100, overlap_chars=20, min_chunk_chars=20)
    )
    return {
        "include_content": True,
        "resources": [
            {
                "resource_id": "test-resource",
                "documents": [
                    {
                        "document_id": "test-document",
                        "text": original,
                        # Represents source attachment bytes rather than extracted text.
                        "content_hash": "f" * 64,
                        "chunks": [
                            {
                                "chunk_id": f"test-chunk-{item.chunk_index}",
                                "content_hash": item.text_hash,
                                "text": item.text,
                                "char_start": item.char_start,
                                "char_end": item.char_end,
                            }
                            for item in parts
                        ],
                    }
                ],
            }
        ],
    }


def test_russian_crlf_blank_lines_nbsp_and_multichunk_are_verified() -> None:
    source = (
        "  Извещение о закупке:   поставка оборудования. \r\n\r\n"
        + "  Требуется\u00a0обеспечение исполнения контракта. " * 9
    )
    result = audit_chunk_export(_export(source))
    assert result.verified, result.error_codes
    assert result.chunks >= 2
    assert result.chunks == result.matching_chunk_hashes
    assert result.chunks == result.matching_normalized_offsets


def test_tampered_hash_fails_without_disclosing_content() -> None:
    data = _export("Техническое задание. " * 20)
    data["resources"][0]["documents"][0]["chunks"][0]["content_hash"] = hashlib.sha256(
        b"wrong"
    ).hexdigest()
    result = audit_chunk_export(data)
    assert not result.verified
    assert "CHUNK_HASH_MISMATCH_OR_MISSING_TEXT" in result.error_codes
    assert all("Техническое" not in code for code in result.error_codes)


def test_tampered_offsets_fail_even_with_correct_chunk_hash() -> None:
    data = _export("Техническое задание. " * 20)
    data["resources"][0]["documents"][0]["chunks"][0]["char_start"] = 1
    result = audit_chunk_export(data)
    assert not result.verified
    assert "NORMALIZED_OFFSET_MISMATCH" in result.error_codes


def test_metadata_only_export_never_counts_as_verified() -> None:
    data = _export("Техническое задание. " * 20)
    data["include_content"] = False
    for doc in data["resources"][0]["documents"]:
        doc["text"] = None
        for chunk in doc["chunks"]:
            chunk["text"] = None
    result = audit_chunk_export(data)
    assert not result.verified
    assert "CONTENT_NOT_INCLUDED" in result.error_codes
    assert "MISSING_DOCUMENT_TEXT" in result.error_codes


def test_missing_source_ids_and_no_chunks_fail_closed() -> None:
    data = _export("Техническое задание. " * 20)
    data["resources"][0]["resource_id"] = ""
    data["resources"][0]["documents"][0]["chunks"][0]["chunk_id"] = None
    report = audit_chunk_export(data)
    assert not report.verified
    assert "MISSING_RESOURCE_ID" in report.error_codes
    assert "MISSING_CHUNK_ID" in report.error_codes
    empty = copy.deepcopy(data)
    empty["resources"][0]["documents"][0]["chunks"] = []
    report = audit_chunk_export(empty)
    assert not report.verified
    assert "NO_CHUNKS" in report.error_codes


def test_invalid_boolean_offsets_and_malformed_export_fail_closed() -> None:
    data = _export("Техническое задание. " * 20)
    data["resources"][0]["documents"][0]["chunks"][0]["char_end"] = True
    assert not audit_chunk_export(data).verified
    bad = audit_chunk_export({"include_content": True, "resources": None})
    assert bad.error_codes == ("MALFORMED_RESOURCES",)
