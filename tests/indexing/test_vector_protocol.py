from arvectum_data.indexing import JsonVectorStore, VectorIndex, VectorSearchResult


def test_json_vector_store_satisfies_vector_index_contract_and_deletes(tmp_path) -> None:
    store = JsonVectorStore(tmp_path / "vectors.json", dimension=2)

    assert isinstance(store, VectorIndex)

    store.upsert("a", (1.0, 0.0), {"collection_id": "one"})
    store.upsert("b", (0.0, 1.0), {"collection_id": "one"})
    assert store.has_vector("a")
    assert store.delete("a") is True
    assert store.delete("a") is False

    hits = store.search((0.0, 1.0), limit=5)
    assert hits == [
        VectorSearchResult(
            vector_id="b",
            score=1.0,
            metadata={"collection_id": "one"},
        )
    ]
