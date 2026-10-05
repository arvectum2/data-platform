from arvectum_data.memory import MemoryConflictPolicy, MemoryKind, MemoryWrite, build_memory_ingest


def test_memory_kinds_are_explicit():
    assert {item.value for item in MemoryKind} == {
        "source_evidence",
        "agent_observation",
        "user_memory",
    }


def test_memory_ingest_preserves_producer_and_model_identity():
    result = build_memory_ingest(
        MemoryWrite(
            collection_id="memory:shared",
            text="Tender 42 requires a signed attachment.",
            kind=MemoryKind.AGENT_OBSERVATION,
            producer="tender-agent",
            source_chunk_ids=("chunk-1",),
            model_provider="local",
            model_name="qwen",
            model_version="1",
            subject_key="tender:42:signature",
            conflict_policy=MemoryConflictPolicy.SUPERSEDE,
        ),
        memory_id="fixed",
    )
    assert result.resource.source_type == "memory"
    assert result.resource.metadata["memory_kind"] == "agent_observation"
    assert result.document.metadata["producer"] == "tender-agent"
    assert result.document.metadata["model_name"] == "qwen"
    assert result.resource.canonical_uri == "memory://memory:shared/fixed"
