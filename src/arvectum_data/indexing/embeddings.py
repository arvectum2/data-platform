from __future__ import annotations

import hashlib
import math
import re
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import ClassVar


_TOKEN_RE = re.compile(r"[\w\-]+", re.UNICODE)


class BaseEmbeddingProvider:
    provider_name: ClassVar[str] = "base"
    model_name: ClassVar[str] = "base"
    dimension: ClassVar[int | None] = 0

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]


class EmbeddingProviderError(RuntimeError):
    """Base error for embedding providers."""


class EmbeddingServerUnavailableError(EmbeddingProviderError):
    """Raised when the local embedding server cannot be reached."""


@dataclass
class HashingEmbeddingProvider(BaseEmbeddingProvider):
    provider_name: ClassVar[str] = "hashing"
    model_name: str = "local-hash-v1"
    dimension: int = 256

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = _TOKEN_RE.findall(text.lower())
        for token in tokens:
            token_weight = 1.0 + min(len(token), 24) / 24.0
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign * token_weight
            if len(token) >= 6:
                char_digest = hashlib.sha256(token[:6].encode("utf-8")).digest()
                char_bucket = int.from_bytes(char_digest[:4], "big") % self.dimension
                char_sign = 1.0 if char_digest[4] % 2 == 0 else -1.0
                vector[char_bucket] += char_sign * 0.5
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]


@dataclass
class SentenceTransformersEmbeddingProvider(BaseEmbeddingProvider):
    model_name: str
    provider_name: ClassVar[str] = "sentence_transformers"

    def __post_init__(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:  # pragma: no cover - optional dependency path
            raise RuntimeError(
                "sentence-transformers is not installed. "
                "Install it locally or switch AI_CORP_RAG_EMBEDDINGS_PROVIDER=hashing."
            ) from exc
        self._model = SentenceTransformer(self.model_name)
        self.dimension = int(self._model.get_sentence_embedding_dimension())

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return [list(map(float, vector)) for vector in vectors]


class LlamaCppEmbeddingProvider(BaseEmbeddingProvider):
    provider_name: ClassVar[str] = "llama_cpp"

    def __init__(
        self,
        model_name: str,
        base_url: str,
        timeout_seconds: int = 60,
        dimension: int | None = None,
    ) -> None:
        self.model_name = model_name
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.dimension = dimension

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        payload = {
            "model": self.model_name,
            "input": texts,
        }
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/embeddings",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise EmbeddingProviderError(
                    f"llama.cpp embedding server is not available at {self.base_url}"
                ) from exc
            raise EmbeddingProviderError(
                f"llama.cpp embedding request failed with HTTP {exc.code} at {self.base_url}"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise EmbeddingServerUnavailableError(
                f"llama.cpp embedding server is not available at {self.base_url}"
            ) from exc

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EmbeddingProviderError(
                f"llama.cpp embedding server returned non-JSON response from {self.base_url}"
            ) from exc

        data = payload.get("data")
        if not isinstance(data, list) or not data:
            raise EmbeddingProviderError("llama.cpp embedding server returned empty embeddings")

        vectors: list[list[float]] = []
        for item in data:
            embedding = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(embedding, list) or not embedding:
                raise EmbeddingProviderError("llama.cpp embedding server returned empty embeddings")
            try:
                vectors.append([float(value) for value in embedding])
            except (TypeError, ValueError) as exc:
                raise EmbeddingProviderError("llama.cpp embedding server returned invalid embedding values") from exc

        if len(vectors) != len(texts):
            raise EmbeddingProviderError(
                f"llama.cpp embedding server returned {len(vectors)} embeddings for {len(texts)} inputs"
            )

        dims = {len(vector) for vector in vectors}
        if len(dims) != 1:
            raise EmbeddingProviderError("llama.cpp embedding batch returned inconsistent dimensions")

        batch_dimension = dims.pop()
        if self.dimension is None:
            self.dimension = batch_dimension
        elif self.dimension != batch_dimension:
            raise EmbeddingProviderError(
                f"llama.cpp embedding dimension changed from {self.dimension} to {batch_dimension}"
            )
        return vectors


def probe_embedding_provider(provider: BaseEmbeddingProvider, *, test_text: str = "ping") -> dict:
    started = time.perf_counter()
    try:
        vector = provider.embed_query(test_text)
    except Exception as exc:
        return {
            "provider": provider.provider_name,
            "base_url": getattr(provider, "base_url", None),
            "model": provider.model_name,
            "reachable": False,
            "test_embedding_dimension": None,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": str(exc),
        }
    return {
        "provider": provider.provider_name,
        "base_url": getattr(provider, "base_url", None),
        "model": provider.model_name,
        "reachable": True,
        "test_embedding_dimension": len(vector),
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "error": None,
    }


def resolve_embedding_dimension(value: str | int | None, *, default: int | None = None) -> int | None:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    lowered = str(value).strip().lower()
    if not lowered or lowered == "auto":
        return None
    return int(lowered)


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str = "hashing"
    model: str = "local-hash-v1"
    base_url: str = "http://127.0.0.1:8090/v1"
    timeout_seconds: int = 60
    dimension: str | int | None = "auto"


def build_embedding_provider(config: EmbeddingConfig) -> BaseEmbeddingProvider:
    provider = (config.provider or "hashing").strip().lower()
    if provider in {"hash", "hashing", "local_hash"}:
        return HashingEmbeddingProvider(
            model_name=config.model or "local-hash-v1",
            dimension=resolve_embedding_dimension(config.dimension, default=256) or 256,
        )
    if provider == "llama_cpp":
        return LlamaCppEmbeddingProvider(
            model_name=config.model or "Qwen3-Embedding-4B",
            base_url=config.base_url or "http://127.0.0.1:8090/v1",
            timeout_seconds=int(config.timeout_seconds or 60),
            dimension=resolve_embedding_dimension(config.dimension),
        )
    if provider == "sentence_transformers":
        return SentenceTransformersEmbeddingProvider(
            model_name=config.model or "intfloat/multilingual-e5-small",
        )
    raise RuntimeError(f"Unsupported embeddings provider: {config.provider}")
