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


def test_trace_counts_distinct_batches_but_not_retries_on_success():
    from arvectum_data.api.ingest_observability import (
        IngestTrace, begin, end, phase_readiness,
    )
    trace = IngestTrace(chunks=5, status_code=200)
    provider = _Provider()
    token = begin(trace)
    try:
        vectors, attempts = _runner(provider, size=2)._embed_texts_with_retry(
            ["one", "two", "three", "four", "five"]
        )
    finally:
        end(token)
    assert len(vectors) == 5 and attempts == 3 and len(provider.calls) == 3
    assert trace.embedding_batches == 3
    assert trace.embedding_retries == 0
    sample = trace.numeric_sample()
    assert sample["embedding_batches"] == 3
    assert sample["embedding_retries"] == 0
    assert sample["embedding_attempts"] == 0  # caller sets historical counter
    summary = phase_readiness([sample])["total"]
    assert summary["embedding_batches_sum"] == 3
    assert summary["embedding_retries_sum"] == 0
    assert summary["requests_with_embedding_retries"] == 0


def test_retry_counts_only_repeated_submission_not_next_batch():
    from arvectum_data.api.ingest_observability import IngestTrace, begin, end

    class Flaky(_Provider):
        def embed_texts(self, texts):
            self.calls.append(tuple(texts))
            if tuple(texts) == ("three",) and self.calls.count(("three",)) == 1:
                raise EmbeddingServerUnavailableError("retry-able")
            return [[1.0, 2.0] for _ in texts]

    trace = IngestTrace()
    provider = Flaky()
    token = begin(trace)
    try:
        vectors, attempts = _runner(provider, size=2)._embed_texts_with_retry(
            ["one", "two", "three"]
        )
    finally:
        end(token)
    assert len(vectors) == 3 and attempts == 3
    assert provider.calls == [("one", "two"), ("three",), ("three",)]
    assert trace.embedding_batches == 2
    assert trace.embedding_retries == 1


def test_exhausted_retries_remain_visible_on_failed_ingest():
    from arvectum_data.api.ingest_observability import IngestTrace, begin, end

    class Down(_Provider):
        def embed_texts(self, texts):
            self.calls.append(tuple(texts))
            raise EmbeddingServerUnavailableError("PRIVATE_ENDPOINT_UNAVAILABLE")

    trace = IngestTrace(status_code=503)
    provider = Down()
    token = begin(trace)
    try:
        with pytest.raises(EmbeddingServerUnavailableError):
            _runner(provider, size=4, retries=3)._embed_texts_with_retry(["one", "two"])
    finally:
        end(token)
    assert len(provider.calls) == 3
    assert trace.embedding_batches == 1 and trace.embedding_retries == 2
    assert trace.numeric_sample()["embedding_attempts"] == 0
    assert "PRIVATE_ENDPOINT" not in str(trace.numeric_sample())


def test_old_sample_compatibility_and_context_isolation():
    from arvectum_data.api.ingest_observability import (
        IngestTrace, begin, end, phase_readiness,
    )
    trace = IngestTrace()
    token = begin(trace)
    try:
        _runner(_Provider(), size=2)._embed_texts_with_retry(["a", "b", "c"])
    finally:
        end(token)
    assert trace.embedding_batches == 2 and trace.embedding_retries == 0
    _runner(_Provider(), size=2)._embed_texts_with_retry(["d", "e", "f"])
    assert trace.embedding_batches == 2
    old = trace.numeric_sample()
    old.pop("embedding_batches")
    old.pop("embedding_retries")
    report = phase_readiness([old, trace.numeric_sample()])
    assert report["total"]["embedding_batches_sum"] == 2
    assert report["total"]["embedding_retries_sum"] == 0
    assert report["total"]["embedding_attempts_sum"] == 0
    assert report["by_chunk_count"]["unknown_or_zero"]["embedding_batches_sum"] == 2


def test_authenticated_get_exposes_numeric_batch_retry_counts_only():
    from fastapi.testclient import TestClient

    from arvectum_data.api.app import create_app
    from arvectum_data.api.config import Settings
    from arvectum_data.api.ingest_observability import IngestTrace

    app = create_app(
        Settings(environment="test", log_level="WARNING", internal_api_key="secret")
    )
    trace = IngestTrace(
        chunks=2, embedding_attempts=4, embedding_batches=2,
        embedding_retries=2, total_ms=100, status_code=200,
    )
    app.state.ingest_phase_samples.append(trace.numeric_sample())
    client = TestClient(app)
    assert client.get("/v1/support/readiness").status_code == 401
    response = client.get(
        "/v1/support/readiness", headers={"X-Arvectum-Key": "secret"}
    )
    assert response.status_code == 200
    payload = response.json()["ingest_phases"]
    assert payload["total"]["embedding_batches_sum"] == 2
    assert payload["total"]["embedding_retries_sum"] == 2
    assert payload["total"]["requests_with_embedding_retries"] == 1
    assert payload["total"]["embedding_attempts_sum"] == 4
    assert payload["by_chunk_count"]["one_to_three"]["embedding_retries_sum"] == 2
    assert "PRIVATE_ENDPOINT" not in response.text
