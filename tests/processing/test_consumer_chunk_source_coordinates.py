"""Frozen v1 contract for actual chunk offset space and exact content hashes."""

from __future__ import annotations

import hashlib

from arvectum_data.processing.chunking import ChunkingConfig, chunk_text, normalize_text


def test_chunk_offsets_are_normalized_not_extracted_source():
    original = "  Раздел  1.\r\n\r\n  Срок   оплаты: семь рабочих дней.\u00a0 "
    cleaned = normalize_text(original)
    assert cleaned == "Раздел 1. Срок оплаты: семь рабочих дней."
    assert cleaned not in original
    chunks = chunk_text(original, ChunkingConfig(min_chunk_chars=1, chunk_size_chars=80))
    assert len(chunks) == 1
    chunk = chunks[0]
    assert (chunk.char_start, chunk.char_end) == (0, len(cleaned))
    assert chunk.text == cleaned
    assert chunk.text_hash == hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()


def test_boundary_strip_does_not_invent_original_offsets():
    original = "  аванс   10 процентов,  оплата после акта.  "
    normalized = normalize_text(original)
    chunks = chunk_text(original, ChunkingConfig(min_chunk_chars=1, chunk_size_chars=15, overlap_chars=0))
    assert chunks
    for chunk in chunks:
        assert 0 <= chunk.char_start <= chunk.char_end <= len(normalized)
        assert chunk.text == normalized[chunk.char_start:chunk.char_end].strip()
        assert chunk.text_hash == hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
    assert len(original) > len(normalized)
