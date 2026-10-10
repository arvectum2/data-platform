"""Bounded embedding calls, retries and cross-batch dimensional invariants."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from arvectum_data.api.service_mixins.retrieval import RetrievalServiceMixin
from arvectum_data.api.service_support import EmbeddingContractMismatch
from arvectum_data.indexing import EmbeddingServerUnavailableError


class _Provider:
    def __init__(self):
        self.calls = []

    def embed_texts(self, texts):
        self.calls.append(tuple(texts))
        return [[float(len(t)), 1.0] for t in texts]


def _runner(provider, *, size=2, chars=1024, retries=3):
    service = RetrievalServiceMixin()
    service.settings = SimpleNamespace(
        embedding_inference_batch_size=size,
        embedding_inference_batch_chars=chars,
        embedding_retry_max_attempts=retries,
        embedding_retry_max_delay_seconds=0,
        embedding_retry_base_delay_seconds=0,
    )
    service.embedding_provider = provider
    return service


def test_batch_size_preserves_order_and_counts_model_calls():
    provider = _Provider()
    vectors, attempts = _runner(provider)._embed_texts_with_retry(["one", "two", "three", "four", "five"])
    assert provider.calls == [("one", "two"), ("three", "four"), ("five",)]
    assert [v[0] for v in vectors] == [3, 3, 5, 4, 4]
    assert attempts == 3


def test_char_budget_and_oversize_chunk_are_not_truncated():
    provider = _Provider()
    texts = ["x" * 700, "y" * 800, "z" * 1100, "a" * 3]
    vectors, attempts = _runner(provider, size=4, chars=1024)._embed_texts_with_retry(texts)
    assert provider.calls == [(texts[0],), (texts[1],), (texts[2],), (texts[3],)]
    assert len(vectors) == 4 and attempts == 4


def test_retry_is_scoped_to_failed_batch_only():
    class Flaky(_Provider):
        def embed_texts(self, texts):
            self.calls.append(tuple(texts))
            if texts[0] == "third" and self.calls.count(tuple(texts)) == 1:
                raise EmbeddingServerUnavailableError("transient")
            return [[1.0, 2.0] for _ in texts]

    provider = Flaky()
    vectors, attempts = _runner(provider)._embed_texts_with_retry(["first", "second", "third"])
    assert len(vectors) == 3 and attempts == 3
    assert provider.calls == [("first", "second"), ("third",), ("third",)]


def test_dimension_inconsistency_across_batches_is_rejected():
    class Bad(_Provider):
        def embed_texts(self, texts):
            return [[1.0] * (3 if texts[0] == "third" else 2) for _ in texts]

    with pytest.raises(EmbeddingContractMismatch, match="inconsistent dimensions"):
        _runner(Bad())._embed_texts_with_retry(["first", "second", "third"])


def test_failing_batch_does_not_retry_unrelated_errors():
    class Bad(_Provider):
        def embed_texts(self, texts):
            self.calls.append(tuple(texts))
            raise RuntimeError("bad contract")

    provider = Bad()
    with pytest.raises(RuntimeError, match="bad contract"):
        _runner(provider)._embed_texts_with_retry(["one", "two", "three"])
    assert provider.calls == [("one", "two")]


def test_empty_batch_does_not_call_provider():
    provider = _Provider()
    assert _runner(provider)._embed_texts_with_retry([]) == ([], 0)
    assert provider.calls == []


def test_validation_settings_reject_unbounded_batch_sizes():
    from arvectum_data.api.config import Settings
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(_env_file=None, embedding_inference_batch_size=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, embedding_inference_batch_chars=0)
