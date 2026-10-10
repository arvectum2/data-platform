"""Search deduplication must retain original SDK/consumer facades."""

from arvectum_data.api.search_hit_policy import (
    _collapse_canonical_hits,
    _dedupe_federated_hits,
)
from arvectum_data.api.service_mixins.retrieval import RetrievalServiceMixin


def test_existing_consumer_facade_preserved():
    assert RetrievalServiceMixin._collapse_canonical_hits is _collapse_canonical_hits
    assert RetrievalServiceMixin._dedupe_federated_hits is _dedupe_federated_hits
