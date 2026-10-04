from arvectum_data.storage.postgres import Base


def test_canonical_storage_tables_are_registered() -> None:
    assert {
        "dp_collections",
        "dp_resources",
        "dp_documents",
        "dp_records",
        "dp_chunks",
        "dp_chunk_embeddings",
        "dp_provenance",
        "dp_pipeline_runs",
    }.issubset(Base.metadata.tables)
