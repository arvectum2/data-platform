from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .models import BackendHit


_TOKEN_RE = re.compile(r"[\w\-]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class MemorySearchDocument:
    chunk_id: str
    document_id: str
    resource_id: str
    collection_id: str
    canonical_uri: str
    title: str
    text: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


class InMemoryLexicalBackend:
    def __init__(self, documents: Sequence[MemorySearchDocument] = ()):
        self.documents = list(documents)

    def search_lexical(
        self,
        query: str,
        *,
        collections: Sequence[str],
        filters: Mapping[str, Sequence[str]] | None,
        limit: int,
    ) -> list[BackendHit]:
        tokens = [token.casefold() for token in _TOKEN_RE.findall(query)]
        if not tokens or limit < 1:
            return []
        collection_set = set(collections)
        scored: list[BackendHit] = []
        for document in self.documents:
            if document.collection_id not in collection_set:
                continue
            if not self._matches_filters(document, filters):
                continue
            haystack = f"{document.title} {document.text}".casefold()
            score = 0.0
            if query.casefold() in haystack:
                score += 5.0
            for token in tokens:
                count = haystack.count(token)
                if count:
                    score += 1.0 + min(count, 8) * 0.25
            if score <= 0:
                continue
            scored.append(
                BackendHit(
                    chunk_id=document.chunk_id,
                    document_id=document.document_id,
                    resource_id=document.resource_id,
                    canonical_uri=document.canonical_uri,
                    title=document.title,
                    text=document.text,
                    score=score,
                    metadata={
                        **dict(document.metadata),
                        "collection_id": document.collection_id,
                    },
                )
            )
        scored.sort(key=lambda item: (-item.score, item.chunk_id))
        return scored[:limit]

    @staticmethod
    def _matches_filters(
        document: MemorySearchDocument,
        filters: Mapping[str, Sequence[str]] | None,
    ) -> bool:
        for key, values in (filters or {}).items():
            if key not in document.metadata:
                return False
            if str(document.metadata[key]) not in {str(value) for value in values}:
                return False
        return True
