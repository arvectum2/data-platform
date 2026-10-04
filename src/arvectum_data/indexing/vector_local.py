from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SearchResult:
    vector_id: str
    score: float
    metadata: dict


class JsonVectorStore:
    def __init__(self, path: str | Path, *, dimension: int | None = None):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._dimension = dimension
        self._vectors: dict[str, dict] = {}
        self._loaded = False

    @property
    def path(self) -> Path:
        return self._path

    @property
    def dimension(self) -> int | None:
        self._ensure_loaded()
        return self._dimension

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if self._path.exists():
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            self._dimension = payload.get("dimension", self._dimension)
            self._vectors = payload.get("vectors", {})
        self._loaded = True

    def persist(self) -> None:
        self._ensure_loaded()
        payload = {
            "dimension": self._dimension,
            "vectors": self._vectors,
        }
        self._path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def has_vector(self, vector_id: str) -> bool:
        self._ensure_loaded()
        return vector_id in self._vectors

    def upsert(self, vector_id: str, vector: list[float], metadata: dict | None = None) -> None:
        self._ensure_loaded()
        if self._dimension is None:
            self._dimension = len(vector)
        elif self._dimension != len(vector):
            raise RuntimeError(
                f"Vector dimension mismatch: expected {self._dimension}, got {len(vector)}"
            )
        self._vectors[vector_id] = {
            "values": vector,
            "metadata": metadata or {},
        }

    def search(
        self,
        query_vector: list[float],
        *,
        limit: int = 10,
        allowed_vector_ids: set[str] | None = None,
    ) -> list[SearchResult]:
        self._ensure_loaded()
        if self._dimension is None or not self._vectors:
            return []
        if len(query_vector) != self._dimension:
            raise RuntimeError(
                f"Query vector dimension mismatch: expected {self._dimension}, got {len(query_vector)}"
            )
        query_norm = _vector_norm(query_vector)
        if query_norm == 0:
            return []

        scored: list[SearchResult] = []
        for vector_id, payload in self._vectors.items():
            if allowed_vector_ids is not None and vector_id not in allowed_vector_ids:
                continue
            vector = payload.get("values", [])
            score = _cosine_similarity(query_vector, query_norm, vector)
            scored.append(
                SearchResult(
                    vector_id=vector_id,
                    score=score,
                    metadata=payload.get("metadata", {}),
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:limit]


def _vector_norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def _cosine_similarity(query: list[float], query_norm: float, doc: list[float]) -> float:
    doc_norm = _vector_norm(doc)
    if query_norm == 0 or doc_norm == 0:
        return 0.0
    dot = sum(q * d for q, d in zip(query, doc))
    return dot / (query_norm * doc_norm)
