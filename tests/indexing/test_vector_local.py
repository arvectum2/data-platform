from arvectum_data.indexing import JsonVectorStore


def test_json_vector_store_persists_filters_and_searches(tmp_path) -> None:
    path = tmp_path / "vectors.json"
    store = JsonVectorStore(path, dimension=2)
    store.upsert("a", [1.0, 0.0], {"collection_id": "one"})
    store.upsert("b", [0.0, 1.0], {"collection_id": "two"})
    store.persist()

    reopened = JsonVectorStore(path)
    all_hits = reopened.search([1.0, 0.0], limit=2)
    scoped = reopened.search([1.0, 0.0], limit=2, allowed_vector_ids={"b"})

    assert [hit.vector_id for hit in all_hits] == ["a", "b"]
    assert [hit.vector_id for hit in scoped] == ["b"]
    assert reopened.dimension == 2
