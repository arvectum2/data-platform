import math

from arvectum_data.indexing import (
    EmbeddingConfig,
    HashingEmbeddingProvider,
    LlamaCppEmbeddingProvider,
    build_embedding_provider,
    probe_embedding_provider,
)


def test_hashing_embeddings_are_deterministic_and_normalized() -> None:
    provider = HashingEmbeddingProvider(dimension=64)

    first = provider.embed_query("силовой кабель ввгнг")
    second = provider.embed_query("силовой кабель ввгнг")

    assert first == second
    assert len(first) == 64
    assert math.isclose(math.sqrt(sum(value * value for value in first)), 1.0)


def test_builder_is_product_neutral() -> None:
    provider = build_embedding_provider(
        EmbeddingConfig(provider="hashing", model="test-hash", dimension=32)
    )

    assert provider.provider_name == "hashing"
    assert provider.model_name == "test-hash"
    assert provider.dimension == 32


def test_probe_reports_provider_health() -> None:
    result = probe_embedding_provider(HashingEmbeddingProvider(dimension=16))

    assert result["reachable"] is True
    assert result["test_embedding_dimension"] == 16


def test_llama_provider_tracks_dimension(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"data":[{"embedding":[1,2,3]}]}'

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    provider = LlamaCppEmbeddingProvider(
        model_name="test",
        base_url="http://127.0.0.1:8090/v1",
        dimension=None,
    )

    assert provider.embed_query("hello") == [1.0, 2.0, 3.0]
    assert provider.dimension == 3
