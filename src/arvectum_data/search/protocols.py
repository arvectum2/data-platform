from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from .models import BackendHit


class LexicalBackend(Protocol):
    def search_lexical(
        self,
        query: str,
        *,
        collections: Sequence[str],
        filters: Mapping[str, Sequence[str]] | None,
        limit: int,
    ) -> list[BackendHit]: ...


class VectorBackend(Protocol):
    def search_vector(
        self,
        query_vector: Sequence[float],
        *,
        collections: Sequence[str],
        filters: Mapping[str, Sequence[str]] | None,
        provider: str,
        model: str,
        limit: int,
    ) -> list[BackendHit]: ...
