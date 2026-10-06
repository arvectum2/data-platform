from __future__ import annotations

import json

import httpx
import pytest

from arvectum_data_client import DataPlatformClient, DataPlatformError


def _client(handler) -> DataPlatformClient:
    transport = httpx.MockTransport(handler)
    return DataPlatformClient(
        base_url="http://data-platform.test",
        api_key="internal-secret",
        consumer="growth-agent",
        consumer_key="consumer-secret",
        client=httpx.Client(
            base_url="http://data-platform.test",
            transport=transport,
            headers={"X-Arvectum-Key": "internal-secret"},
        ),
    )


def test_contract_and_required_major() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Arvectum-Key"] == "internal-secret"
        assert request.url.path == "/v1/contract"
        return httpx.Response(
            200,
            json={
                "name": "arvectum-data-consumer",
                "version": "1.0",
                "api_prefix": "/v1",
                "capabilities": ["search"],
                "internal_api_key_header": "X-Arvectum-Key",
                "consumer_id_header": "X-Arvectum-Consumer",
                "consumer_key_header": "X-Arvectum-Consumer-Key",
            },
        )

    client = _client(handler)
    assert client.require_contract(1)["version"] == "1.0"


def test_search_preserves_consumer_identity_and_contract_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/search"
        assert request.headers["X-Arvectum-Consumer"] == "growth-agent"
        assert request.headers["X-Arvectum-Consumer-Key"] == "consumer-secret"
        payload = json.loads(request.content)
        assert payload["query"] == "кабель"
        assert payload["collections"] == ["growth:products"]
        assert payload["vector_weight"] == 4.0
        return httpx.Response(
            200,
            json={
                "query": "кабель",
                "hits": [
                    {
                        "chunk_id": "chunk-1",
                        "document_id": "doc-1",
                        "resource_id": "resource-1",
                        "canonical_uri": "https://example.com/product",
                        "title": "Кабель",
                        "preview": "Кабель силовой",
                        "text": "Кабель силовой",
                        "scores": {
                            "lexical": 0.5,
                            "vector": 0.8,
                            "fusion": 0.9,
                        },
                        "evidence": [],
                        "metadata": {},
                    }
                ],
            },
        )

    client = _client(handler)
    hits = client.search(
        query="кабель",
        collections=["growth:products"],
        limit=5,
        vector_weight=4.0,
    )
    assert hits[0]["scores"]["fusion"] == 0.9


def test_process_document_uses_multipart_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/process/document"
        content_type = request.headers["Content-Type"]
        assert content_type.startswith("multipart/form-data;")
        body = request.content
        assert b'name="collection_id"' in body
        assert b"test:processing" in body
        assert b"sample.txt" in body
        return httpx.Response(
            200,
            json={
                "resource_id": "resource-1",
                "document_id": "doc-1",
                "collection_id": "test:processing",
                "canonical_uri": "test://sample",
                "title": "sample",
                "media_type": "text/plain",
                "extraction_status": "extracted",
                "text": "hello",
                "chunks": [
                    {
                        "chunk_id": "chunk-1",
                        "ordinal": 0,
                        "text": "hello",
                        "content_hash": "hash",
                        "char_start": 0,
                        "char_end": 5,
                        "token_estimate": 1,
                    }
                ],
            },
        )

    client = _client(handler)
    payload = client.process_document(
        collection_id="test:processing",
        canonical_uri="test://sample",
        title="sample",
        content=b"hello",
        filename="sample.txt",
        content_type="text/plain",
        min_chunk_chars=1,
    )
    assert payload["extraction_status"] == "extracted"
    assert payload["chunks"][0]["chunk_id"] == "chunk-1"


def test_http_error_exposes_status_method_and_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "database unavailable"})

    client = _client(handler)
    with pytest.raises(DataPlatformError) as exc_info:
        client.collection_stats("missing")
    assert exc_info.value.status_code == 503
    assert exc_info.value.method == "GET"
    assert exc_info.value.path == "/v1/collections/missing/stats"


def test_collection_naming_helper_is_domain_neutral() -> None:
    from arvectum_data_client import build_collection_id

    assert build_collection_id("domain", "scope", "rev1") == "domain:scope:rev1"
    with pytest.raises(ValueError, match="must not contain"):
        build_collection_id("domain", "bad:scope")


def test_search_with_profile_forwards_consumer_owned_weights() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["mode"] == "hybrid"
        assert payload["lexical_weight"] == 1.0
        assert payload["vector_weight"] == 4.0
        assert payload["query_variant_weight"] == 0.7
        assert payload["collapse_by_canonical_uri"] is True
        assert payload["rerank_strategy"] == "cross_encoder"
        return httpx.Response(200, json={"query": "q", "hits": []})

    client = _client(handler)
    assert client.search_with_profile(
        query="q",
        collections=["domain:scope:rev1"],
        limit=10,
        profile={
            "mode": "hybrid",
            "lexical_weight": 1.0,
            "vector_weight": 4.0,
            "query_variant_weight": 0.7,
            "collapse_by_canonical_uri": True,
        },
    ) == []


def test_connector_credential_sdk_contract() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        assert request.headers["X-Arvectum-Consumer"] == "growth-agent"
        assert request.headers["X-Arvectum-Consumer-Key"] == "consumer-secret"
        if request.url.path == "/v1/connectors/credentials":
            if request.method == "POST":
                payload = json.loads(request.content)
                assert payload["connector"] == "private-search"
                assert payload["secrets"] == {"api_key": "secret"}
                return httpx.Response(
                    200,
                    json={
                        "credential_id": "cred-1",
                        "tenant_id": "tenant-1",
                        "consumer_id": "growth-agent",
                        "connector": "private-search",
                        "label": "key",
                        "status": "active",
                        "metadata": {},
                        "created_at": "2026-10-06T00:00:00Z",
                        "revoked_at": None,
                    },
                )
            return httpx.Response(200, json=[])
        if request.url.path == "/v1/discover":
            payload = json.loads(request.content)
            assert payload["credential_id"] == "cred-1"
            return httpx.Response(
                200,
                json={"resources": [], "next_cursor": None, "warnings": []},
            )
        raise AssertionError(request.url.path)

    client = _client(handler)
    created = client.create_connector_credential(
        connector="private-search",
        secrets={"api_key": "secret"},
        label="key",
    )
    assert created["credential_id"] == "cred-1"
    assert client.list_connector_credentials() == []
    assert client.discover(
        connector="private-search",
        query="supplier",
        credential_id="cred-1",
    )["resources"] == []
    assert calls == [
        ("POST", "/v1/connectors/credentials"),
        ("GET", "/v1/connectors/credentials"),
        ("POST", "/v1/discover"),
    ]
