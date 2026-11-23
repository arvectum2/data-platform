"""Guardrail tests for optional, bounded, same-collection embedding reuse."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from arvectum_data.api.config import Settings
from arvectum_data.api.embedding_reuse import EmbeddingReuseCache


def _chunk(text: str, chunk_id: str):
    return SimpleNamespace(
        chunk_id=chunk_id,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        text=text,
    )


def _provider(*, model: str = "Qwen3", dimension: int | None = 3):
    return SimpleNamespace(provider_name="llama_cpp", model_name=model, dimension=dimension)


def test_default_off_and_bounded_config() -> None:
    assert Settings(_env_file=None).embedding_reuse_cache_entries == 0
    cache = EmbeddingReuseCache()
    provider = _provider()
    c = _chunk("identical exact text", "id-one")
    cache.put_many("collection-a", provider, [c], {"id-one": [1, 2, 3]})
    assert cache.size() == 0
    assert cache.get_many("collection-a", provider, [c]) == {}
    from pydantic import ValidationError

    for value in (-1, 513):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, embedding_reuse_cache_entries=value)


def test_scope_and_content_hash_exact_and_no_plaintext_retention() -> None:
    cache = EmbeddingReuseCache(capacity=2)
    provider = _provider()
    doc_a = _chunk("identical exact text", "document-a")
    doc_b = _chunk("identical exact text", "document-b")
    other = _chunk("different text entirely", "document-other")
    cache.put_many("collection-a", provider, [doc_a], {"document-a": [1, 2, 3]})
    assert cache.get_many("collection-a", provider, [doc_b]) == {"document-b": [1.0, 2.0, 3.0]}
    assert cache.get_many("collection-b", provider, [doc_b]) == {}
    assert cache.get_many("collection-a", provider, [other]) == {}
    assert "identical exact text" not in repr(cache._entries)
    result = cache.get_many("collection-a", provider, [doc_b])
    result["document-b"][0] = -3
    assert cache.get_many("collection-a", provider, [doc_b])["document-b"][0] == 1
    assert cache.get_many("collection-a", _provider(), [doc_b]) == {}
    # Switching providers invalidates old cache entries rather than relying
    # on id() uniqueness after a future Python object-id reuse.
    assert cache.get_many("collection-a", provider, [doc_b]) == {}


def test_provider_dimension_contract_and_fail_closed_entries() -> None:
    cache = EmbeddingReuseCache(capacity=8)
    unknown = _provider(dimension=None)
    item = _chunk("same source chunk", "original")
    cache.put_many("one", unknown, [item], {"original": [1, 2, 3]})
    assert cache.size() == 0
    p = _provider()
    cache.put_many("one", p, [item], {"original": [1, 2]})
    assert cache.size() == 0
    cache.put_many("one", p, [item], {"original": [1, 2, 3]})
    assert cache.size() == 1
    p.dimension = 4
    assert cache.get_many("one", p, [item]) == {}
    p.dimension = 3
    p.model_name = "Qwen3-v2"
    assert cache.get_many("one", p, [item]) == {}


def test_ttl_and_lru_eviction() -> None:
    now = [30.0]
    cache = EmbeddingReuseCache(capacity=2, ttl_seconds=5, clock=lambda: now[0])
    p = _provider()
    a, b, c = (_chunk(name, name) for name in ("a", "b", "c"))
    cache.put_many("collection", p, [a, b], {"a": [1, 2, 3], "b": [4, 5, 6]})
    assert cache.get_many("collection", p, [a])["a"] == [1, 2, 3]
    cache.put_many("collection", p, [c], {"c": [7, 8, 9]})
    assert cache.get_many("collection", p, [b]) == {}
    assert cache.get_many("collection", p, [a])
    now[0] += 5
    assert cache.get_many("collection", p, [a]) == {}
    assert cache.size() <= 2


def test_concurrent_cache_ops_remain_bounded() -> None:
    cache = EmbeddingReuseCache(capacity=8)
    p = _provider()

    def do_one(i: int) -> None:
        item = _chunk(f"content {i % 90}", f"id-{i}")
        cache.put_many("collection", p, [item], {item.chunk_id: [1, 2, 3]})
        found = cache.get_many("collection", p, [item])
        assert not found or found[item.chunk_id] == [1, 2, 3]

    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(do_one, range(240)))
    assert 0 < cache.size() <= 8
