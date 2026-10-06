from __future__ import annotations

from fastapi.testclient import TestClient

from arvectum_data.api.app import create_app
from arvectum_data.api.config import Settings
from arvectum_data.api.service import UnsafeUrlError, validate_public_http_url
from arvectum_data.engine import AutoDiscoveryProvider, ExtractionEngine, RawAsset
from arvectum_data.search import (
    SearchEvidence,
    SearchHit,
    SearchScores,
)


class FakePlatformService:
    def status(self):
        return {
            "status": "ok",
            "database_configured": True,
            "embedding_provider": "hashing",
            "embedding_model": "local-hash-v1",
            "embedding_dimension": 16,
        }

    def create_collection(
        self,
        *,
        collection_id,
        owner,
        name,
        default_language,
        access_policy=None,
        retention_policy=None,
    ):
        return {
            "collection_id": collection_id,
            "owner": owner,
            "name": name,
            "default_language": default_language,
            "embedding_provider": "hashing",
            "embedding_model": "local-hash-v1",
            "embedding_dimension": 16,
            "active_index_revision": None,
            "access_policy": dict(access_policy or {}),
            "retention_policy": dict(retention_policy or {}),
        }

    def get_collection(self, collection_id):
        return self.create_collection(
            collection_id=collection_id,
            owner="tests",
            name="Test",
            default_language="simple",
        )

    def export_collection(
        self,
        collection_id,
        *,
        include_content=False,
        offset=0,
        limit=100,
    ):
        return {
            "collection": self.get_collection(collection_id),
            "include_content": include_content,
            "offset": offset,
            "limit": limit,
            "total_resources": 1,
            "has_more": False,
            "resources": [],
        }

    def prune_collection_retention(self, collection_id, *, dry_run=True):
        return {
            "collection_id": collection_id,
            "dry_run": dry_run,
            "max_age_days": 30,
            "cutoff_at": "2026-09-06T00:00:00Z",
            "matched_resources": 0,
            "deleted_resources": 0,
        }

    def delete_collection(self, collection_id, *, confirm=False):
        return {
            "collection_id": collection_id,
            "confirmed": confirm,
            "deleted": confirm,
            "counts": {
                "resources": 1,
                "documents": 1,
                "chunks": 1,
                "embeddings": 1,
            },
        }

    def collection_stats(self, collection_id):
        return {
            "collection_id": collection_id,
            "resources": 1,
            "documents": 1,
            "chunks": 1,
            "embeddings": 1,
        }

    def process_document_bytes(
        self,
        *,
        collection_id,
        filename,
        content,
        title=None,
        canonical_uri=None,
        chunk_size_chars=1500,
        overlap_chars=200,
        min_chunk_chars=120,
        max_chars=2_000_000,
    ):
        assert content
        return {
            "collection_id": collection_id,
            "resource_id": "resource-process-1",
            "document_id": "document-process-1",
            "canonical_uri": canonical_uri or f"upload://{filename}",
            "title": title or filename,
            "media_type": "text/plain",
            "extraction_status": "extracted",
            "text": "processed text",
            "chunks": [
                {
                    "chunk_id": "chunk-process-1",
                    "ordinal": 0,
                    "text": "processed text",
                    "content_hash": "hash-process-1",
                    "char_start": 0,
                    "char_end": 14,
                    "token_estimate": 3,
                }
            ],
        }

    def ingest_document_bytes(
        self,
        *,
        collection_id,
        filename,
        content,
        title=None,
        canonical_uri=None,
        pre_chunked=False,
    ):
        assert content
        return {
            "collection_id": collection_id,
            "resource_id": "resource-1",
            "document_id": "document-1",
            "chunks": 1,
            "embeddings": 1,
            "canonical_uri": canonical_uri or f"upload://{filename}",
        }

    def ingest_url(self, *, collection_id, url, title=None):
        return {
            "collection_id": collection_id,
            "resource_id": "resource-url",
            "document_id": "document-url",
            "chunks": 1,
            "embeddings": 1,
            "canonical_uri": url,
        }

    def connector_status(self):
        return [
            {
                "name": "fake",
                "state": "ready",
                "capabilities": ["discover"],
                "detail": "test connector",
                "metadata": {},
            }
        ]

    def discover(self, *, connector_name, query, cursor=None, limit=10):
        from arvectum_data.connectors import DiscoveryPage, DiscoveredResource

        assert connector_name == "fake"
        return DiscoveryPage(
            resources=(
                DiscoveredResource(
                    canonical_uri="https://example.com/result",
                    provider="fake",
                    title=query,
                    rank=1,
                ),
            )
        )

    def research(
        self,
        *,
        query,
        collection_id,
        connector="duckduckgo_html",
        source_limit=8,
        evidence_limit=8,
        consumer=None,
        rerank=False,
        expand_query=False,
    ):
        from arvectum_data.answers import GroundedAnswer
        from arvectum_data.research import ResearchResult, ResearchStageDiagnostic

        return ResearchResult(
            query=query,
            answer=GroundedAnswer(
                answer=None,
                claims=(),
                contradictions=(),
                uncertainty="reasoning disabled",
                abstained=True,
            ),
            sources=(),
            evidence=(),
            warnings=(),
            diagnostics=(
                ResearchStageDiagnostic(
                    stage="discovery",
                    status="executed",
                    duration_ms=5.0,
                    provider=connector,
                    metadata={"resources": 0, "warnings": 0},
                ),
                ResearchStageDiagnostic(
                    stage="total-research",
                    status="executed",
                    duration_ms=12.0,
                    metadata={"sources": 0, "evidence": 0},
                ),
            ),
        )

    def rebuild_index(self, collection_id):
        return {
            "run_id": "job-1",
            "collection_id": collection_id,
            "run_type": "reindex",
            "revision": "revision-1",
            "status": "completed",
            "metrics": {"chunks_seen": 1, "embeddings_written": 1},
            "started_at": "2026-10-04T10:00:00Z",
            "completed_at": "2026-10-04T10:00:01Z",
        }

    def get_index_job(self, run_id):
        result = self.rebuild_index("tests:knowledge")
        result["run_id"] = run_id
        return result

    def list_index_jobs(self, *, collection_id=None, limit=50):
        return [self.rebuild_index(collection_id or "tests:knowledge")]

    def create_entity(self, *, entity_type, canonical_name, aliases=(), metadata=None):
        return {
            "entity_id": "entity-1",
            "entity_type": entity_type,
            "canonical_name": canonical_name,
            "aliases": [
                {
                    "alias_id": "alias-1",
                    "alias_kind": "name",
                    "value": canonical_name,
                    "normalized_value": canonical_name.casefold(),
                    "source_collection_id": None,
                    "metadata": {"canonical": True},
                    "created_at": "2026-10-04T10:00:00Z",
                }
            ],
            "metadata": dict(metadata or {}),
            "created_at": "2026-10-04T10:00:00Z",
            "updated_at": "2026-10-04T10:00:00Z",
        }

    def get_entity(self, entity_id):
        result = self.create_entity(
            entity_type="supplier",
            canonical_name="Example Supplier",
        )
        result["entity_id"] = entity_id
        return result

    def resolve_entity(self, *, entity_type, value, alias_kind="name", limit=20):
        candidate = self.create_entity(
            entity_type=entity_type,
            canonical_name=value,
        )
        return {
            "status": "resolved",
            "normalized_value": value.casefold(),
            "candidates": [candidate][:limit],
        }

    def create_entity_relation(self, **kwargs):
        return {
            "relation_id": "r" * 64,
            "source_entity_id": kwargs["source_entity_id"],
            "target_entity_id": kwargs["target_entity_id"],
            "relation_type": kwargs["relation_type"],
            "source_collection_id": kwargs.get("source_collection_id"),
            "resource_id": kwargs.get("resource_id"),
            "document_id": kwargs.get("document_id"),
            "chunk_id": kwargs.get("chunk_id"),
            "metadata": dict(kwargs.get("metadata") or {}),
            "created_at": "2026-10-04T10:00:00Z",
        }

    def list_entity_relations(
        self,
        entity_id,
        *,
        direction="both",
        relation_type=None,
        status="canonical",
        limit=100,
    ):
        relation = self.create_entity_relation(
            source_entity_id=entity_id,
            target_entity_id="entity-2",
            relation_type=relation_type or "related_to",
        )
        return [relation][:limit]

    def record_relevance_feedback(self, **kwargs):
        return {
            "feedback_id": "feedback-1",
            "collection_id": kwargs["collection_id"],
            "resource_id": kwargs["resource_id"],
            "document_id": kwargs["document_id"],
            "chunk_id": kwargs["chunk_id"],
            "query_hash": "a" * 64,
            "label": kwargs["label"],
            "rank": kwargs.get("rank"),
            "actor": kwargs.get("actor"),
            "context": dict(kwargs.get("context") or {}),
            "created_at": "2026-10-04T10:00:00Z",
        }

    def list_relevance_feedback(self, *, collection_id, limit=100):
        return [
            self.record_relevance_feedback(
                collection_id=collection_id,
                resource_id="resource-1",
                document_id="document-1",
                chunk_id="chunk-1",
                query="needle",
                label="relevant",
                rank=1,
                actor="tests",
                context={"surface": "unit"},
            )
        ][:limit]

    def relevance_feedback_summary(self, collection_id):
        return {
            "collection_id": collection_id,
            "total": 1,
            "relevant": 1,
            "partially_relevant": 0,
            "not_relevant": 0,
        }

    def search(self, request, *, consumer=None):
        return [
            SearchHit(
                chunk_id="chunk-1",
                document_id="document-1",
                resource_id="resource-1",
                canonical_uri="https://example.com/doc",
                title="Document",
                preview="preview",
                text="full text",
                scores=SearchScores(lexical=0.5, vector=0.8, fusion=0.03),
                evidence=(
                    SearchEvidence(
                        resource_id="resource-1",
                        document_id="document-1",
                        chunk_id="chunk-1",
                        canonical_uri="https://example.com/doc",
                    ),
                ),
                metadata={"collection_id": request.collections[0]},
            )
        ]

    def extract(
        self,
        *,
        asset_id,
        source_url,
        text,
        html,
        attributes,
        fields,
    ):
        return ExtractionEngine((AutoDiscoveryProvider(),)).extract(
            RawAsset(
                asset_id=asset_id,
                source_url=source_url,
                text=text,
                html=html,
                attributes=attributes,
            ),
            fields,
        )


def _client(
    *,
    key: str = "secret",
    consumer_api_keys: dict[str, str] | None = None,
) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                environment="test",
                log_level="WARNING",
                internal_api_key=key,
                consumer_api_keys=consumer_api_keys or {},
            ),
            platform_service=FakePlatformService(),
        )
    )


def test_v1_requires_internal_api_key_but_health_stays_public() -> None:
    client = _client()

    assert client.get("/health").status_code == 200
    assert client.get("/v1/status").status_code == 401
    response = client.get("/v1/status", headers={"X-Arvectum-Key": "secret"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    assert response.json()["requests"] >= 2


def test_consumer_contract_is_versioned_and_capability_driven() -> None:
    client = _client()
    response = client.get(
        "/v1/contract",
        headers={"X-Arvectum-Key": "secret"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "arvectum-data-consumer"
    assert payload["version"] == "1.0"
    assert payload["api_prefix"] == "/v1"
    assert {
        "collections",
        "document_process",
        "document_ingest",
        "url_ingest",
        "search",
        "discovery",
        "entities",
        "entity_relations",
    }.issubset(set(payload["capabilities"]))


def test_collection_ingest_search_and_extract_contracts() -> None:
    client = _client()
    headers = {"X-Arvectum-Key": "secret"}

    created = client.post(
        "/v1/collections",
        headers=headers,
        json={
            "collection_id": "tests:knowledge",
            "owner": "tests",
            "name": "Knowledge",
            "default_language": "russian",
            "access_policy": {"allowed_consumers": ["growth-agent"]},
        },
    )
    assert created.status_code == 200
    assert created.json()["collection_id"] == "tests:knowledge"

    stats = client.get(
        "/v1/collections/tests:knowledge/stats",
        headers=headers,
    )
    assert stats.status_code == 200
    assert stats.json()["resources"] == 1
    assert stats.json()["embeddings"] == 1

    processed = client.post(
        "/v1/process/document",
        headers=headers,
        data={
            "collection_id": "tests:knowledge",
            "canonical_uri": "tender-document://doc-1",
            "chunk_size_chars": "1500",
            "overlap_chars": "200",
            "min_chunk_chars": "120",
        },
        files={"file": ("knowledge.txt", b"short", "text/plain")},
    )
    assert processed.status_code == 200
    processed_body = processed.json()
    assert processed_body["extraction_status"] == "extracted"
    assert processed_body["text"] == "processed text"
    assert processed_body["chunks"][0]["ordinal"] == 0

    ingested = client.post(
        "/v1/ingest/document",
        headers=headers,
        data={
            "collection_id": "tests:knowledge",
            "canonical_uri": "tender-document://doc-1",
            "pre_chunked": "true",
        },
        files={"file": ("knowledge.txt", b"short", "text/plain")},
    )
    assert ingested.status_code == 200
    assert ingested.json()["embeddings"] == 1
    assert ingested.json()["canonical_uri"] == "tender-document://doc-1"

    searched = client.post(
        "/v1/search",
        headers=headers,
        json={
            "query": "кабель",
            "collections": ["tests:knowledge"],
            "mode": "hybrid",
        },
    )
    assert searched.status_code == 200
    hit = searched.json()["hits"][0]
    assert hit["scores"]["lexical"] == 0.5
    assert hit["scores"]["vector"] == 0.8
    assert hit["evidence"][0]["resource_id"] == "resource-1"

    extracted = client.post(
        "/v1/extract",
        headers=headers,
        json={
            "asset_id": "asset-1",
            "text": "Price: 1999",
            "fields": [
                {
                    "key": "price",
                    "required": True,
                    "aliases": ["Price"],
                    "min_confidence": 0.5,
                }
            ],
        },
    )
    assert extracted.status_code == 200
    assert extracted.json()["values"]["price"] == "1999"


def test_status_exposes_secret_free_operation_metrics() -> None:
    app = create_app(
        Settings(
            environment="test",
            log_level="WARNING",
            internal_api_key="super-secret-key",
            database_url="postgresql+psycopg://user:password@example.invalid/db",
        ),
        platform_service=FakePlatformService(),
    )
    client = TestClient(app)
    headers = {"X-Arvectum-Key": "super-secret-key"}

    ingested = client.post(
        "/v1/ingest/document",
        headers=headers,
        data={"collection_id": "tests:knowledge", "pre_chunked": "true"},
        files={"file": ("knowledge.txt", b"short", "text/plain")},
    )
    assert ingested.status_code == 200

    searched = client.post(
        "/v1/search",
        headers=headers,
        json={
            "query": "кабель",
            "collections": ["tests:knowledge"],
            "mode": "hybrid",
        },
    )
    assert searched.status_code == 200

    discovered = client.post(
        "/v1/discover",
        headers=headers,
        json={"connector": "fake", "query": "needle", "limit": 5},
    )
    assert discovered.status_code == 200

    rebuilt = client.post(
        "/v1/index/rebuild",
        headers=headers,
        json={"collection_id": "tests:knowledge"},
    )
    assert rebuilt.status_code == 200

    unauthorized_search = client.post(
        "/v1/search",
        json={
            "query": "кабель",
            "collections": ["tests:knowledge"],
            "mode": "hybrid",
        },
    )
    assert unauthorized_search.status_code == 401

    status = client.get("/v1/status", headers=headers)
    assert status.status_code == 200
    payload = status.json()

    for operation in ("ingest", "search", "discover", "reindex"):
        metric = payload["operations"][operation]
        assert metric["requests"] >= 1
        assert metric["total_ms"] >= 0
        assert metric["max_ms"] >= 0

    assert payload["operations"]["search"]["requests"] == 2
    assert payload["operations"]["search"]["errors"] == 1

    serialized = status.text
    assert "super-secret-key" not in serialized
    assert "password" not in serialized
    assert "postgresql+psycopg" not in serialized
    assert "example.invalid" not in serialized


def test_capacity_guardrails_fail_closed_before_heavy_work() -> None:
    upload_client = TestClient(
        create_app(
            Settings(
                environment="test",
                log_level="WARNING",
                database_url="",
                max_upload_bytes=4,
            )
        )
    )
    too_large = upload_client.post(
        "/v1/ingest/document",
        data={"collection_id": "tests:knowledge"},
        files={"file": ("large.txt", b"12345", "text/plain")},
    )
    assert too_large.status_code == 413

    chunk_client = TestClient(
        create_app(
            Settings(
                environment="test",
                log_level="WARNING",
                database_url="",
                max_upload_bytes=100_000,
                max_chunks_per_ingest=1,
            )
        )
    )
    too_many_chunks = chunk_client.post(
        "/v1/ingest/document",
        data={"collection_id": "tests:knowledge"},
        files={
            "file": (
                "many-chunks.txt",
                ("capacity guardrail text " * 500).encode("utf-8"),
                "text/plain",
            )
        },
    )
    assert too_many_chunks.status_code == 400
    assert "max_chunks_per_ingest=1" in too_many_chunks.json()["detail"]

    search_client = TestClient(
        create_app(
            Settings(
                environment="test",
                log_level="WARNING",
                internal_api_key="secret",
                max_search_collections=2,
            ),
            platform_service=FakePlatformService(),
        )
    )
    too_many_collections = search_client.post(
        "/v1/search",
        headers={"X-Arvectum-Key": "secret"},
        json={
            "query": "кабель",
            "collections": ["one", "two", "three"],
            "mode": "hybrid",
        },
    )
    assert too_many_collections.status_code == 413


def test_federated_search_requires_consumer_scoped_credentials() -> None:
    client = _client(consumer_api_keys={"growth-agent": "growth-secret"})
    headers = {"X-Arvectum-Key": "secret"}
    payload = {
        "query": "needle",
        "collections": ["tests:knowledge", "tests:secondary"],
        "mode": "hybrid",
    }

    missing = client.post("/v1/search", headers=headers, json=payload)
    assert missing.status_code == 403

    invalid = client.post(
        "/v1/search",
        headers={
            **headers,
            "X-Arvectum-Consumer": "growth-agent",
            "X-Arvectum-Consumer-Key": "wrong",
        },
        json=payload,
    )
    assert invalid.status_code == 403

    valid = client.post(
        "/v1/search",
        headers={
            **headers,
            "X-Arvectum-Consumer": "growth-agent",
            "X-Arvectum-Consumer-Key": "growth-secret",
        },
        json=payload,
    )
    assert valid.status_code == 200
    assert valid.json()["hits"]


def test_entity_resolution_contract() -> None:
    client = _client()
    headers = {"X-Arvectum-Key": "secret"}

    created = client.post(
        "/v1/entities",
        headers=headers,
        json={
            "entity_type": "supplier",
            "canonical_name": "ООО Ромашка",
            "aliases": [
                {
                    "alias_kind": "identifier",
                    "value": "7701234567",
                    "metadata": {"scheme": "inn"},
                }
            ],
            "metadata": {"source": "test"},
        },
    )
    assert created.status_code == 200
    entity_id = created.json()["entity_id"]
    assert created.json()["entity_type"] == "supplier"

    fetched = client.get(f"/v1/entities/{entity_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["entity_id"] == entity_id

    resolved = client.post(
        "/v1/entities/resolve",
        headers=headers,
        json={
            "entity_type": "supplier",
            "value": "ООО Ромашка",
            "alias_kind": "name",
        },
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["candidates"]


def test_entity_relation_contract() -> None:
    client = _client()
    headers = {"X-Arvectum-Key": "secret"}

    created = client.post(
        "/v1/entity-relations",
        headers=headers,
        json={
            "source_entity_id": "entity-1",
            "target_entity_id": "entity-2",
            "relation_type": "supplies",
            "source_collection_id": "tests:knowledge",
            "resource_id": "resource-1",
            "document_id": "document-1",
            "chunk_id": "chunk-1",
            "metadata": {"source": "unit"},
        },
    )
    assert created.status_code == 200
    assert len(created.json()["relation_id"]) == 64

    listed = client.get(
        "/v1/entities/entity-1/relations?direction=outbound&relation_type=supplies",
        headers=headers,
    )
    assert listed.status_code == 200
    assert listed.json()[0]["relation_type"] == "supplies"


def test_relevance_feedback_contract() -> None:
    client = _client()
    headers = {"X-Arvectum-Key": "secret"}

    recorded = client.post(
        "/v1/feedback/relevance",
        headers=headers,
        json={
            "collection_id": "tests:knowledge",
            "resource_id": "resource-1",
            "document_id": "document-1",
            "chunk_id": "chunk-1",
            "query": "кабель для промышленного объекта",
            "label": "relevant",
            "rank": 1,
            "actor": "tests",
            "context": {"surface": "unit"},
        },
    )
    assert recorded.status_code == 200
    assert recorded.json()["label"] == "relevant"
    assert recorded.json()["query_hash"] == "a" * 64
    assert "query" not in recorded.json()

    listed = client.get(
        "/v1/feedback/relevance?collection_id=tests%3Aknowledge",
        headers=headers,
    )
    assert listed.status_code == 200
    assert listed.json()[0]["chunk_id"] == "chunk-1"

    summary = client.get(
        "/v1/feedback/relevance/summary?collection_id=tests%3Aknowledge",
        headers=headers,
    )
    assert summary.status_code == 200
    assert summary.json()["total"] == 1
    assert summary.json()["relevant"] == 1

    invalid = client.post(
        "/v1/feedback/relevance",
        headers=headers,
        json={
            "collection_id": "tests:knowledge",
            "resource_id": "resource-1",
            "document_id": "document-1",
            "chunk_id": "chunk-1",
            "query": "needle",
            "label": "maybe",
        },
    )
    assert invalid.status_code == 422



def test_real_process_document_endpoint_uses_platform_extraction_and_chunking() -> None:
    app = create_app(
        Settings(
            environment="test",
            log_level="WARNING",
            database_url="",
            max_upload_bytes=100_000,
        )
    )
    client = TestClient(app)
    text = ("Оплата производится после приемки товара. " * 12).encode("utf-8")

    response = client.post(
        "/v1/process/document",
        data={
            "collection_id": "tests:processing",
            "canonical_uri": "tender-document://doc-real-1",
            "chunk_size_chars": "180",
            "overlap_chars": "20",
            "min_chunk_chars": "40",
        },
        files={"file": ("contract.txt", text, "text/plain")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["collection_id"] == "tests:processing"
    assert payload["canonical_uri"] == "tender-document://doc-real-1"
    assert payload["extraction_status"] == "extracted"
    assert "Оплата производится после приемки товара." in payload["text"]
    assert len(payload["chunks"]) >= 2
    assert payload["chunks"][0]["ordinal"] == 0
    assert payload["chunks"][0]["content_hash"]

def test_openapi_exposes_core_v1_contract() -> None:
    client = _client()
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]

    assert "/v1/collections" in paths
    assert "/v1/collections/{collection_id}/stats" in paths
    assert "/v1/ingest/url" in paths
    assert "/v1/ingest/document" in paths
    assert "/v1/process/document" in paths
    assert "/v1/search" in paths
    assert "/v1/entities" in paths
    assert "/v1/entities/resolve" in paths
    assert "/v1/entities/{entity_id}" in paths
    assert "/v1/entity-relations" in paths
    assert "/v1/entities/{entity_id}/relations" in paths
    assert "/v1/feedback/relevance" in paths
    assert "/v1/connectors" in paths
    assert "/v1/discover" in paths
    assert "/v1/extract" in paths


def test_unconfigured_service_returns_503_for_data_endpoint() -> None:
    client = TestClient(
        create_app(
            Settings(
                environment="test",
                log_level="WARNING",
                database_url="",
            )
        )
    )
    response = client.post(
        "/v1/collections",
        json={
            "collection_id": "tests:knowledge",
            "owner": "tests",
            "name": "Knowledge",
        },
    )
    assert response.status_code == 503


def test_url_guard_rejects_loopback() -> None:
    try:
        validate_public_http_url("http://127.0.0.1/test")
    except UnsafeUrlError:
        pass
    else:
        raise AssertionError("loopback URL must be rejected")


def test_connector_discovery_contract() -> None:
    client = _client()
    headers = {"X-Arvectum-Key": "secret"}

    status = client.get("/v1/connectors", headers=headers)
    assert status.status_code == 200
    assert status.json()[0]["name"] == "fake"

    discovered = client.post(
        "/v1/discover",
        headers=headers,
        json={"connector": "fake", "query": "needle", "limit": 5},
    )
    assert discovered.status_code == 200
    item = discovered.json()["resources"][0]
    assert item["canonical_uri"] == "https://example.com/result"
    assert item["title"] == "needle"


def test_openapi_exposes_stable_v1_paths() -> None:
    client = _client(key="")
    paths = client.get("/openapi.json").json()["paths"]

    assert "/v1/collections" in paths
    assert "/v1/ingest/url" in paths
    assert "/v1/ingest/document" in paths
    assert "/v1/process/document" in paths
    assert "/v1/extract" in paths
    assert "/v1/search" in paths


def test_index_job_contracts() -> None:
    client = _client()
    headers = {"X-Arvectum-Key": "secret"}

    rebuilt = client.post(
        "/v1/index/rebuild",
        headers=headers,
        json={"collection_id": "tests:knowledge"},
    )
    assert rebuilt.status_code == 200
    assert rebuilt.json()["status"] == "completed"

    job = client.get("/v1/index/jobs/job-1", headers=headers)
    assert job.status_code == 200
    assert job.json()["metrics"]["embeddings_written"] == 1

    jobs = client.get(
        "/v1/index/jobs?collection_id=tests%3Aknowledge",
        headers=headers,
    )
    assert jobs.status_code == 200
    assert jobs.json()[0]["collection_id"] == "tests:knowledge"

def test_execution_modes_are_discoverable_and_enforce_search_depth() -> None:
    client = _client()
    headers = {"X-Arvectum-Key": "secret"}

    modes = client.get("/v1/modes", headers=headers)
    assert modes.status_code == 200
    payload = {item["mode"]: item for item in modes.json()["modes"]}
    assert set(payload) == {"fast", "standard", "deep", "research"}
    assert payload["fast"]["optional_stages"] == []
    assert payload["standard"]["optional_stages"] == ["rerank"]
    assert payload["deep"]["optional_stages"] == ["query-expansion", "rerank"]
    assert payload["research"]["endpoint"] == "/v1/research"
    assert payload["fast"]["latency_budget_ms"] == 500
    assert payload["standard"]["max_model_calls"] == 1
    assert payload["deep"]["latency_budget_ms"] == 2500
    assert payload["research"]["latency_budget_ms"] == 120000

    fast = client.post(
        "/v1/search",
        headers=headers,
        json={
            "query": "кабель",
            "collections": ["tests:knowledge"],
            "execution_mode": "fast",
        },
    )
    assert fast.status_code == 200
    assert fast.json()["execution_mode"] == "fast"
    assert fast.json()["diagnostics"]["execution_mode"] == "fast"
    assert fast.json()["diagnostics"]["latency_budget_ms"] == 500
    assert fast.json()["diagnostics"]["max_model_calls"] == 0

    fast_rerank = client.post(
        "/v1/search",
        headers=headers,
        json={
            "query": "кабель",
            "collections": ["tests:knowledge"],
            "execution_mode": "fast",
            "rerank": True,
        },
    )
    assert fast_rerank.status_code == 422

    standard_expansion = client.post(
        "/v1/search",
        headers=headers,
        json={
            "query": "кабель",
            "collections": ["tests:knowledge"],
            "execution_mode": "standard",
            "expand_query": True,
        },
    )
    assert standard_expansion.status_code == 422

    research_search = client.post(
        "/v1/search",
        headers=headers,
        json={
            "query": "кабель",
            "collections": ["tests:knowledge"],
            "execution_mode": "research",
        },
    )
    assert research_search.status_code == 422


def test_legacy_search_without_execution_mode_keeps_manual_flags_compatible() -> None:
    client = _client()
    response = client.post(
        "/v1/search",
        headers={"X-Arvectum-Key": "secret"},
        json={
            "query": "кабель",
            "collections": ["tests:knowledge"],
            "expand_query": True,
            "query_expansion_limit": 8,
            "rerank": True,
            "rerank_candidates": 100,
        },
    )

    assert response.status_code == 200
    assert response.json()["execution_mode"] is None

def test_research_execution_mode_exposes_safe_budget_diagnostics() -> None:
    client = _client()
    response = client.post(
        "/v1/research",
        headers={"X-Arvectum-Key": "secret"},
        json={
            "query": "research-secret-marker",
            "collection_id": "tests:knowledge",
            "connector": "fake",
            "execution_mode": "research",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["execution_mode"] == "research"
    diagnostics = body["diagnostics"]
    assert diagnostics["latency_budget_ms"] == 120000
    assert diagnostics["max_model_calls"] == 3
    assert diagnostics["within_latency_budget"] is True
    assert diagnostics["total_ms"] == 12.0
    assert [item["stage"] for item in diagnostics["stages"]] == [
        "discovery",
        "total-research",
    ]
    assert "research-secret-marker" not in repr(diagnostics)
