from arvectum_data.search import InMemoryLexicalBackend, MemorySearchDocument


def test_memory_lexical_is_collection_scoped_and_filterable() -> None:
    backend = InMemoryLexicalBackend(
        [
            MemorySearchDocument(
                chunk_id="a",
                document_id="da",
                resource_id="ra",
                collection_id="one",
                canonical_uri="https://example.com/a",
                title="Кабель",
                text="Силовой кабель ВВГнг",
                metadata={"source_type": "web"},
            ),
            MemorySearchDocument(
                chunk_id="b",
                document_id="db",
                resource_id="rb",
                collection_id="two",
                canonical_uri="https://example.com/b",
                title="Кабель",
                text="Силовой кабель ВВГнг",
                metadata={"source_type": "file"},
            ),
        ]
    )

    hits = backend.search_lexical(
        "силовой кабель",
        collections=("one",),
        filters={"source_type": ("web",)},
        limit=10,
    )

    assert [hit.chunk_id for hit in hits] == ["a"]
