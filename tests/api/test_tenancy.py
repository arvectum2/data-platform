from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from arvectum_data.api.app import create_app
from arvectum_data.api.config import Settings
from arvectum_data.api.service import (
    CollectionAccessDenied,
    DataPlatformService,
    TenantQuotaExceeded,
)
from arvectum_data.indexing import HashingEmbeddingProvider
from arvectum_data.search import SearchQuery
from arvectum_data.storage.postgres import CollectionRow


def _service() -> DataPlatformService:
    settings = Settings(
        environment="test",
        log_level="WARNING",
        consumer_api_keys={
            "agent-a": "key-a",
            "agent-a-2": "key-a-2",
            "agent-b": "key-b",
        },
        consumer_tenants={
            "agent-a": "tenant-a",
            "agent-a-2": "tenant-a",
            "agent-b": "tenant-b",
        },
        tenant_quotas={
            "tenant-a": {
                "max_collections_per_search": 2,
                "max_results_per_search": 5,
                "max_rerank_candidates": 5,
                "max_query_variants": 1,
            }
        },
    )
    return DataPlatformService(
        settings,
        embedding_provider=HashingEmbeddingProvider(dimension=16),
    )


def _collection(policy: dict[str, object]) -> CollectionRow:
    return CollectionRow(
        collection_id="tenant:docs",
        owner="tests",
        name="Tenant docs",
        default_language="simple",
        access_policy=policy,
        retention_policy={},
    )


def test_tenant_boundary_allows_multiple_consumers_in_same_tenant() -> None:
    service = _service()
    collection = _collection({"tenant_id": "tenant-a"})

    service._authorize_collection_consumer(collection, "agent-a")
    service._authorize_collection_consumer(collection, "agent-a-2")

    with pytest.raises(CollectionAccessDenied):
        service._authorize_collection_consumer(collection, "agent-b")
    with pytest.raises(CollectionAccessDenied):
        service._authorize_collection_consumer(collection, None)


def test_allowed_consumers_can_narrow_tenant_access() -> None:
    service = _service()
    collection = _collection(
        {
            "tenant_id": "tenant-a",
            "allowed_consumers": ["agent-a"],
        }
    )

    service._authorize_collection_consumer(collection, "agent-a")
    with pytest.raises(CollectionAccessDenied):
        service._authorize_collection_consumer(collection, "agent-a-2")


@pytest.mark.parametrize(
    "search_query",
    [
        SearchQuery(
            query="q",
            collections=("a", "b", "c"),
            limit=5,
        ),
        SearchQuery(
            query="q",
            collections=("a",),
            limit=6,
        ),
        SearchQuery(
            query="q",
            collections=("a",),
            limit=5,
            rerank=True,
            rerank_candidates=6,
        ),
        SearchQuery(
            query="q",
            collections=("a",),
            limit=5,
            query_variants=("v1", "v2"),
        ),
    ],
)
def test_tenant_search_quota_fails_closed(search_query: SearchQuery) -> None:
    service = _service()
    with pytest.raises(TenantQuotaExceeded):
        service._validate_tenant_search_quota(search_query, "agent-a")


def test_unmapped_legacy_consumer_has_no_tenant_quota() -> None:
    service = _service()
    request = SearchQuery(
        query="q",
        collections=("a", "b", "c"),
        limit=25,
    )
    service._validate_tenant_search_quota(request, "legacy-agent")


def test_http_maps_tenant_quota_to_429() -> None:
    class QuotaService:
        def search(self, request, *, consumer=None):
            raise TenantQuotaExceeded("tenant quota exceeded")

    client = TestClient(
        create_app(
            Settings(
                environment="test",
                log_level="WARNING",
                consumer_api_keys={"agent-a": "key-a"},
                consumer_tenants={"agent-a": "tenant-a"},
            ),
            platform_service=QuotaService(),
        )
    )

    response = client.post(
        "/v1/search",
        headers={
            "X-Arvectum-Consumer": "agent-a",
            "X-Arvectum-Consumer-Key": "key-a",
        },
        json={
            "query": "q",
            "collections": ["tenant:docs"],
        },
    )

    assert response.status_code == 429
    assert response.json()["detail"] == "tenant quota exceeded"


def test_reused_resolved_tenant_preserves_allowed_consumers_enforcement() -> None:
    service = _service()
    collection = _collection({
        "tenant_id": "tenant-a", "allowed_consumers": ["agent-a"],
    })
    assert service._validate_tenant_search_quota(
        SearchQuery(query="test", collections=("a",), limit=5), "agent-a"
    ) == "tenant-a"
    service._authorize_collection_consumer(
        collection, "agent-a", resolved_tenant="tenant-a"
    )
    with pytest.raises(CollectionAccessDenied):
        service._authorize_collection_consumer(
            collection, "agent-a-2", resolved_tenant="tenant-a"
        )
    with pytest.raises(CollectionAccessDenied):
        service._authorize_collection_consumer(
            collection, "agent-a", resolved_tenant="tenant-b"
        )
