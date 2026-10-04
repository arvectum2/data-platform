from arvectum_data.processing import ChunkingConfig, chunk_text


def test_chunk_text_creates_overlapping_chunks() -> None:
    text = " ".join(
        f"Раздел {index} содержит уникальные требования к заявке."
        for index in range(40)
    )
    chunks = chunk_text(
        text,
        ChunkingConfig(chunk_size_chars=180, overlap_chars=30, min_chunk_chars=50),
    )

    assert len(chunks) >= 2
    assert chunks[1].char_start < chunks[0].char_end
    assert chunks[0].token_estimate > 0


def test_chunk_text_deduplicates_hashes_and_compacts_indexes() -> None:
    repeated = "A" * 60
    final = "B" * 60
    chunks = chunk_text(
        f"{repeated} {repeated} {final}",
        ChunkingConfig(chunk_size_chars=60, overlap_chars=0, min_chunk_chars=10),
    )

    assert [chunk.text for chunk in chunks] == [repeated, final]
    assert [chunk.chunk_index for chunk in chunks] == [0, 1]
