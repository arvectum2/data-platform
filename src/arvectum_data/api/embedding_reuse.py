"""Opt-in, collection-scoped, content-addressed embedding reuse.

Only numeric vectors and SHA-256 chunk hashes are retained; no document text,
source URI, document ID or tenant credentials. A server process never persists
this bounded, short-lived cache or shares it between collection IDs.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from typing import Any

CacheKey = tuple[str, int, str, str, int, str]


class EmbeddingReuseCache:
    def __init__(
        self,
        capacity: int = 0,
        *,
        ttl_seconds: int = 300,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0 <= capacity <= 512:
            raise ValueError("cache capacity outside safe bounds")
        if not 1 <= ttl_seconds <= 3600:
            raise ValueError("cache TTL outside safe bounds")
        self.capacity = capacity
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: OrderedDict[CacheKey, tuple[float, tuple[float, ...]]] = OrderedDict()

    @staticmethod
    def _key(collection_id: str, provider: Any, content_hash: str) -> CacheKey | None:
        dim = getattr(provider, "dimension", None)
        if type(dim) is not int or dim <= 0:
            return None
        provider_name = getattr(provider, "provider_name", "")
        model_name = getattr(provider, "model_name", "")
        if not collection_id or not provider_name or not model_name or len(content_hash) != 64:
            return None
        # Object identity also prevents reusing vectors after a runtime provider swap
        # under an unchanged public model alias.
        return (collection_id, id(provider), provider_name, model_name, dim, content_hash)

    def get_many(
        self, collection_id: str, provider: Any, chunks: Sequence[Any]
    ) -> dict[str, list[float]]:
        if not self.capacity or not chunks:
            return {}
        result: dict[str, list[float]] = {}
        now = self._clock()
        with self._lock:
            for chunk in chunks:
                key = self._key(collection_id, provider, chunk.content_hash)
                if key is None:
                    continue
                entry = self._entries.get(key)
                if entry is None:
                    continue
                expires_at, vector = entry
                if now >= expires_at:
                    del self._entries[key]
                    continue
                self._entries.move_to_end(key)
                result[chunk.chunk_id] = list(vector)
        return result

    def put_many(
        self,
        collection_id: str,
        provider: Any,
        chunks: Sequence[Any],
        vectors: Mapping[str, Sequence[float]],
    ) -> None:
        if not self.capacity:
            return
        expires = self._clock() + self.ttl_seconds
        with self._lock:
            for chunk in chunks:
                key = self._key(collection_id, provider, chunk.content_hash)
                vector = vectors.get(chunk.chunk_id)
                if key is None or vector is None or len(vector) != key[4]:
                    continue
                self._entries[key] = (expires, tuple(float(v) for v in vector))
                self._entries.move_to_end(key)
                while len(self._entries) > self.capacity:
                    self._entries.popitem(last=False)

    def size(self) -> int:
        with self._lock:
            return len(self._entries)
