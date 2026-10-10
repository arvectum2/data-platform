"""Index revision compatibility gate: existing revision IDs must not drift."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from types import SimpleNamespace

from arvectum_data.api.service_mixins.retrieval import RetrievalServiceMixin


@dataclass(frozen=True)
class _Chunk:
    chunk_id: str
    content_hash: str


def test_streamed_index_revision_matches_pre_refactor_serialization():
    fake = SimpleNamespace(embedding_provider=SimpleNamespace(
        provider_name="hashing", model_name="test", dimension=32,
    ))
    collection = SimpleNamespace(default_language="russian")
    for chunks in ((), (_Chunk("x", "h"),), (_Chunk("б", "7"), _Chunk("a", "8"))):
        old_payload = "\n".join([
            "provider=hashing", "model=test", "dimension=32", "language=russian",
            *[f"{c.chunk_id}:{c.content_hash}" for c in sorted(chunks, key=lambda c: c.chunk_id)],
        ])
        actual = RetrievalServiceMixin._index_revision(fake, collection, chunks)
        assert actual == hashlib.sha256(old_payload.encode("utf-8")).hexdigest()
