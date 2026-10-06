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
