from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from arvectum_data.documents import ingest_file
from arvectum_data.indexing import HashingEmbeddingProvider
from arvectum_data.processing import ChunkingConfig
from arvectum_data.storage.postgres import DataRepository, build_engine


pytestmark = pytest.mark.postgres


def _database_url() -> str:
    value = os.getenv("ARVECTUM_DATA_TEST_DATABASE_URL", "").strip()
    if not value:
        pytest.skip("ARVECTUM_DATA_TEST_DATABASE_URL is not configured")
    return value


def test_migrate_ingest_embed_and_scoped_vector_search(tmp_path: Path) -> None:
    database_url = _database_url()
    os.environ["ARVECTUM_DATA_DATABASE_URL"] = database_url
    config = Config("alembic.ini")
    command.upgrade(config, "head")

    engine = build_engine(database_url)
    tables = set(inspect(engine).get_table_names())
    assert "dp_collections" in tables
    assert "dp_chunk_embeddings" in tables

    path = tmp_path / "knowledge.txt"
    path.write_text(
        ("Силовой кабель ВВГнг для промышленного объекта. " * 80).strip(),
        encoding="utf-8",
    )
    ingest = ingest_file(
        path,
        collection_id="test:knowledge",
        chunking=ChunkingConfig(
            chunk_size_chars=180,
            overlap_chars=30,
            min_chunk_chars=50,
        ),
    )
    provider = HashingEmbeddingProvider(dimension=64)

    with Session(engine) as session:
        repo = DataRepository(session)
        repo.ensure_collection(
            "test:knowledge",
            owner="tests",
            name="Knowledge",
            default_language="russian",
            embedding_provider=provider.provider_name,
            embedding_model=provider.model_name,
            embedding_dimension=provider.dimension,
        )
        repo.ensure_collection(
            "test:other",
            owner="tests",
            name="Other",
            embedding_provider=provider.provider_name,
            embedding_model=provider.model_name,
            embedding_dimension=provider.dimension,
        )
        repo.persist_ingest(ingest)
        for chunk in ingest.chunks:
            repo.upsert_embedding(
                chunk_id=chunk.chunk_id,
                provider=provider.provider_name,
                model=provider.model_name,
                vector=provider.embed_query(chunk.text),
            )
        session.commit()

        hits = repo.search_vectors(
            provider.embed_query("кабель для объекта"),
            collection_id="test:knowledge",
            provider=provider.provider_name,
            model=provider.model_name,
            limit=5,
        )
        other_hits = repo.search_vectors(
            provider.embed_query("кабель для объекта"),
            collection_id="test:other",
            provider=provider.provider_name,
            model=provider.model_name,
            limit=5,
        )
        lexical_hits = repo.search_lexical(
            "силовой кабель",
            collection_id="test:knowledge",
            limit=5,
        )
        lexical_other = repo.search_lexical(
            "силовой кабель",
            collection_id="test:other",
            limit=5,
        )
        lexical_filtered_out = repo.search_lexical(
            "силовой кабель",
            collection_id="test:knowledge",
            filters={"source_type": ("url",)},
            limit=5,
        )

        from arvectum_data.search import (
            HybridSearchEngine,
            PostgresSearchBackend,
            SearchQuery,
        )

        backend = PostgresSearchBackend(repo)
        hybrid_hits = HybridSearchEngine(
            lexical_backend=backend,
            vector_backend=backend,
            embedding_provider=provider,
        ).search(
            SearchQuery(
                query="силовой кабель",
                collections=("test:knowledge",),
                limit=5,
            )
        )

    assert hits
    assert all(hit.canonical_uri == ingest.resource.canonical_uri for hit in hits)
    assert other_hits == []
    assert lexical_hits
    assert all(hit.canonical_uri == ingest.resource.canonical_uri for hit in lexical_hits)
    assert lexical_other == []
    assert lexical_filtered_out == []
    assert hybrid_hits
    assert hybrid_hits[0].scores.lexical is not None
    assert hybrid_hits[0].scores.vector is not None
    assert hybrid_hits[0].evidence
