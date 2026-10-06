from arvectum_data.api.config import Settings
from arvectum_data.api.service import DataPlatformService
from arvectum_data.indexing import HashingEmbeddingProvider


class FakeScorer:
    provider_name = "fake-cross-encoder"
    model_name = "fake-model"
    created = 0

    def __init__(self, model_name):
        type(self).created += 1
        self.model_name = model_name

    def score_pairs(self, pairs):
        return [0.5 for _ in pairs]


def make_service(monkeypatch, model="fake-model"):
    monkeypatch.setattr(
        "arvectum_data.api.service.SentenceTransformersCrossEncoderScorer",
        FakeScorer,
    )
    FakeScorer.created = 0
    return DataPlatformService(
        Settings(
            embedding_provider="hashing",
            embedding_dimension=16,
            cross_encoder_provider="sentence_transformers",
            cross_encoder_model=model,
            cross_encoder_max_candidates=3,
            cross_encoder_max_candidate_chars=1000,
        ),
        embedding_provider=HashingEmbeddingProvider(dimension=16),
    )


def test_cross_encoder_is_lazy_cached_and_bounded(monkeypatch):
    service = make_service(monkeypatch)
    assert service._cross_encoder_scorer is None
    first = service._cross_encoder_reranker(max_candidates=20)
    second = service._cross_encoder_reranker(max_candidates=20)
    assert first.max_candidates == 3
    assert first.max_candidate_chars == 1000
    assert FakeScorer.created == 1
    assert service._cross_encoder_scorer is second.scorer


def test_cross_encoder_blank_model_disables_reranker(monkeypatch):
    service = make_service(monkeypatch, model="")
    assert service._cross_encoder_reranker(max_candidates=3) is None
    assert FakeScorer.created == 0


def test_http_cross_encoder_service_is_lazy_and_configured(monkeypatch):
    created = []

    class FakeHttpScorer:
        provider_name = "http-cross-encoder"

        def __init__(self, *, base_url, model_name, timeout_seconds):
            self.model_name = model_name
            created.append((base_url, model_name, timeout_seconds))

        def score_pairs(self, pairs):
            return [0.5 for _ in pairs]

    monkeypatch.setattr(
        "arvectum_data.api.service.HttpCrossEncoderScorer",
        FakeHttpScorer,
    )
    service = DataPlatformService(
        Settings(
            embedding_provider="hashing",
            embedding_dimension=16,
            cross_encoder_provider="http",
            cross_encoder_model="BAAI/bge-reranker-v2-m3",
            cross_encoder_base_url="http://127.0.0.1:8091",
            cross_encoder_timeout_seconds=0.75,
            cross_encoder_max_candidates=3,
            cross_encoder_max_candidate_chars=1000,
        ),
        embedding_provider=HashingEmbeddingProvider(dimension=16),
    )

    reranker = service._cross_encoder_reranker(max_candidates=20)

    assert reranker is not None
    assert reranker.max_candidates == 3
    assert created == [
        ("http://127.0.0.1:8091", "BAAI/bge-reranker-v2-m3", 0.75)
    ]


def test_disabled_cross_encoder_provider_fails_open_without_initialization():
    service = DataPlatformService(
        Settings(
            embedding_provider="hashing",
            embedding_dimension=16,
            cross_encoder_provider="disabled",
        ),
        embedding_provider=HashingEmbeddingProvider(dimension=16),
    )
    assert service._cross_encoder_reranker(max_candidates=3) is None
