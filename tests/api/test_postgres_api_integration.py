from __future__ import annotations

import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from arvectum_data.api.app import create_app
from arvectum_data.api.config import Settings
from arvectum_data.api.service import DataPlatformService
from arvectum_data.indexing import EmbeddingServerUnavailableError, HashingEmbeddingProvider


pytestmark = pytest.mark.postgres


def _database_url() -> str:
    value = os.getenv("ARVECTUM_DATA_TEST_DATABASE_URL", "").strip()
    if not value:
        pytest.skip("ARVECTUM_DATA_TEST_DATABASE_URL is not configured")
    return value


def test_http_collection_ingest_and_hybrid_search() -> None:
    database_url = _database_url()
    os.environ["ARVECTUM_DATA_DATABASE_URL"] = database_url
    command.upgrade(Config("alembic.ini"), "head")

    app = create_app(
        Settings(
            environment="test",
            log_level="WARNING",
            database_url=database_url,
            internal_api_key="test-secret",
            consumer_api_keys={"growth-agent": "growth-secret"},
            embedding_provider="hashing",
            embedding_model="api-test-hash",
            embedding_dimension=64,
            embedding_retry_max_attempts=3,
            embedding_retry_base_delay_seconds=0,
            embedding_retry_max_delay_seconds=0,
        )
    )
    client = TestClient(app)
    headers = {"X-Arvectum-Key": "test-secret"}

    created = client.post(
        "/v1/collections",
        headers=headers,
        json={
            "collection_id": "api:docs",
            "owner": "tests",
            "name": "API documents",
            "default_language": "russian",
        },
    )
    assert created.status_code == 200

    versioned_collection = client.post(
        "/v1/collections",
        headers=headers,
        json={
            "collection_id": "api:docs:v2",
            "owner": "tests",
            "name": "API documents",
            "default_language": "russian",
        },
    )
    assert versioned_collection.status_code == 200
    assert versioned_collection.json()["collection_id"] == "api:docs:v2"

    content = (
        "Силовой кабель ВВГнг предназначен для промышленного объекта. " * 80
    ).encode("utf-8")
    ingested = client.post(
        "/v1/ingest/document",
        headers=headers,
        data={
            "collection_id": "api:docs",
            "canonical_uri": "external-document://cable-1",
            "pre_chunked": "true",
        },
        files={"file": ("cable.txt", content, "text/plain")},
    )
    assert ingested.status_code == 200
    assert ingested.json()["canonical_uri"] == "external-document://cable-1"
    assert ingested.json()["chunks"] > 0
    assert ingested.json()["embeddings"] == ingested.json()["chunks"]
    assert ingested.json()["embeddings_written"] == ingested.json()["chunks"]
    assert ingested.json()["embeddings_skipped_existing"] == 0

    repeated = client.post(
        "/v1/ingest/document",
        headers=headers,
        data={
            "collection_id": "api:docs",
            "canonical_uri": "external-document://cable-1",
            "pre_chunked": "true",
        },
        files={"file": ("cable.txt", content, "text/plain")},
    )
    assert repeated.status_code == 200
    assert repeated.json()["resource_id"] == ingested.json()["resource_id"]
    assert repeated.json()["document_id"] == ingested.json()["document_id"]
    assert repeated.json()["chunks"] == ingested.json()["chunks"]
    assert repeated.json()["embeddings"] == ingested.json()["embeddings"]
    assert repeated.json()["embeddings_written"] == 0
    assert (
        repeated.json()["embeddings_skipped_existing"]
        == ingested.json()["embeddings"]
    )

    stats = client.get(
        "/v1/collections/api:docs/stats",
        headers=headers,
    )
    assert stats.status_code == 200
    assert stats.json()["resources"] == 1
    assert stats.json()["documents"] == 1
    assert stats.json()["chunks"] == ingested.json()["chunks"]
    assert stats.json()["embeddings"] == ingested.json()["embeddings"]
    assert stats.json()["first_seen_at"] is not None
    assert stats.json()["last_seen_at"] is not None
    assert stats.json()["latest_embedding_at"] is not None

    status = client.get("/v1/status", headers=headers)
    assert status.status_code == 200
    metrics = status.json()["metrics"]
    assert metrics["collections"] >= 1
    assert metrics["resources"] >= 1
    assert metrics["documents"] >= 1
    assert metrics["chunks"] >= 1
    assert metrics["embeddings"] >= 1

    searched = client.post(
        "/v1/search",
        headers=headers,
        json={
            "query": "силовой кабель",
            "collections": ["api:docs"],
            "mode": "hybrid",
            "limit": 5,
        },
    )
    assert searched.status_code == 200
    hits = searched.json()["hits"]
    assert hits
    assert hits[0]["scores"]["lexical"] is not None
    assert hits[0]["scores"]["vector"] is not None
    assert hits[0]["evidence"][0]["canonical_uri"] == "external-document://cable-1"

    canonical_filtered = client.post(
        "/v1/search",
        headers=headers,
        json={
            "query": "силовой кабель",
            "collections": ["api:docs"],
            "filters": {
                "canonical_uri": ["external-document://cable-1"]
            },
            "mode": "hybrid",
            "limit": 5,
        },
    )
    assert canonical_filtered.status_code == 200
    assert canonical_filtered.json()["hits"]
    assert {
        hit["canonical_uri"]
        for hit in canonical_filtered.json()["hits"]
    } == {"external-document://cable-1"}

    protected = client.post(
        "/v1/collections",
        headers=headers,
        json={
            "collection_id": "api:protected",
            "owner": "tests",
            "name": "Protected API documents",
            "default_language": "russian",
            "access_policy": {"allowed_consumers": ["growth-agent"]},
        },
    )
    assert protected.status_code == 200
    assert protected.json()["access_policy"] == {
        "allowed_consumers": ["growth-agent"]
    }

    protected_ingest = client.post(
        "/v1/ingest/document",
        headers=headers,
        data={
            "collection_id": "api:protected",
            "canonical_uri": "external-document://protected-cable",
            "pre_chunked": "true",
        },
        files={
            "file": (
                "protected.txt",
                ("Защищенный документ про силовой кабель. " * 30).encode("utf-8"),
                "text/plain",
            )
        },
    )
    assert protected_ingest.status_code == 200

    protected_denied = client.post(
        "/v1/search",
        headers=headers,
        json={
            "query": "силовой кабель",
            "collections": ["api:protected"],
            "mode": "hybrid",
        },
    )
    assert protected_denied.status_code == 403

    federation_denied = client.post(
        "/v1/search",
        headers=headers,
        json={
            "query": "силовой кабель",
            "collections": ["api:docs", "api:protected"],
            "mode": "hybrid",
        },
    )
    assert federation_denied.status_code == 403

    federation_headers = {
        **headers,
        "X-Arvectum-Consumer": "growth-agent",
        "X-Arvectum-Consumer-Key": "growth-secret",
    }
    federation = client.post(
        "/v1/search",
        headers=federation_headers,
        json={
            "query": "силовой кабель",
            "collections": ["api:docs", "api:protected"],
            "mode": "hybrid",
            "limit": 10,
        },
    )
    assert federation.status_code == 200
    federation_collections = {
        hit["metadata"]["collection_id"] for hit in federation.json()["hits"]
    }
    assert {"api:docs", "api:protected"} <= federation_collections

    first_entity = client.post(
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
        },
    )
    assert first_entity.status_code == 200

    second_entity = client.post(
        "/v1/entities",
        headers=headers,
        json={
            "entity_type": "supplier",
            "canonical_name": "ООО   Ромашка",
            "aliases": [
                {
                    "alias_kind": "identifier",
                    "value": "7807654321",
                    "metadata": {"scheme": "inn"},
                }
            ],
        },
    )
    assert second_entity.status_code == 200

    ambiguous = client.post(
        "/v1/entities/resolve",
        headers=headers,
        json={
            "entity_type": "supplier",
            "value": "  ооо ромашка ",
            "alias_kind": "name",
        },
    )
    assert ambiguous.status_code == 200
    ambiguous_payload = ambiguous.json()
    assert ambiguous_payload["status"] == "ambiguous"
    assert len(ambiguous_payload["candidates"]) == 2

    resolved_identifier = client.post(
        "/v1/entities/resolve",
        headers=headers,
        json={
            "entity_type": "supplier",
            "value": "7701234567",
            "alias_kind": "identifier",
        },
    )
    assert resolved_identifier.status_code == 200
    resolved_payload = resolved_identifier.json()
    assert resolved_payload["status"] == "resolved"
    assert len(resolved_payload["candidates"]) == 1
    assert (
        resolved_payload["candidates"][0]["entity_id"]
        == first_entity.json()["entity_id"]
    )

    unresolved = client.post(
        "/v1/entities/resolve",
        headers=headers,
        json={
            "entity_type": "supplier",
            "value": "9999999999",
            "alias_kind": "identifier",
        },
    )
    assert unresolved.status_code == 200
    assert unresolved.json()["status"] == "unresolved"
    assert unresolved.json()["candidates"] == []

    top_hit = hits[0]
    feedback_query = "силовой кабель для промышленного объекта"
    feedback = client.post(
        "/v1/feedback/relevance",
        headers=headers,
        json={
            "collection_id": "api:docs",
            "resource_id": top_hit["resource_id"],
            "document_id": top_hit["document_id"],
            "chunk_id": top_hit["chunk_id"],
            "query": feedback_query,
            "label": "relevant",
            "rank": 1,
            "actor": "postgres-integration",
            "context": {"surface": "test"},
        },
    )
    assert feedback.status_code == 200
    feedback_payload = feedback.json()
    assert feedback_payload["label"] == "relevant"
    assert feedback_payload["chunk_id"] == top_hit["chunk_id"]
    assert len(feedback_payload["query_hash"]) == 64
    assert "query" not in feedback_payload

    listed_feedback = client.get(
        "/v1/feedback/relevance?collection_id=api%3Adocs",
        headers=headers,
    )
    assert listed_feedback.status_code == 200
    assert listed_feedback.json()[0]["feedback_id"] == feedback_payload["feedback_id"]

    feedback_summary = client.get(
        "/v1/feedback/relevance/summary?collection_id=api%3Adocs",
        headers=headers,
    )
    assert feedback_summary.status_code == 200
    assert feedback_summary.json() == {
        "collection_id": "api:docs",
        "total": 1,
        "relevant": 1,
        "partially_relevant": 0,
        "not_relevant": 0,
    }

    other_collection = client.post(
        "/v1/collections",
        headers=headers,
        json={
            "collection_id": "api:other",
            "owner": "tests",
            "name": "Other API documents",
            "default_language": "russian",
        },
    )
    assert other_collection.status_code == 200
    mismatched_feedback = client.post(
        "/v1/feedback/relevance",
        headers=headers,
        json={
            "collection_id": "api:other",
            "resource_id": top_hit["resource_id"],
            "document_id": top_hit["document_id"],
            "chunk_id": top_hit["chunk_id"],
            "query": feedback_query,
            "label": "not_relevant",
        },
    )
    assert mismatched_feedback.status_code == 400

    rebuilt = client.post(
        "/v1/index/rebuild",
        headers=headers,
        json={"collection_id": "api:docs"},
    )
    assert rebuilt.status_code == 200
    job = rebuilt.json()
    assert job["status"] == "completed"
    assert job["metrics"]["chunks_seen"] > 0
    assert job["metrics"]["embeddings_written"] == job["metrics"]["chunks_seen"]

    fetched_job = client.get(
        f"/v1/index/jobs/{job['run_id']}",
        headers=headers,
    )
    assert fetched_job.status_code == 200
    assert fetched_job.json()["revision"] == job["revision"]

    repeated_rebuild = client.post(
        "/v1/index/rebuild",
        headers=headers,
        json={"collection_id": "api:docs"},
    )
    assert repeated_rebuild.status_code == 200
    repeated_job = repeated_rebuild.json()
    assert repeated_job["run_id"] == job["run_id"]
    assert repeated_job["revision"] == job["revision"]
    assert repeated_job["status"] == "completed"
    assert repeated_job["metrics"] == job["metrics"]

    stats_after_rebuild = client.get(
        "/v1/collections/api:docs/stats",
        headers=headers,
    )
    assert stats_after_rebuild.status_code == 200
    assert stats_after_rebuild.json()["active_index_revision"] == job["revision"]

    second_content = (
        "Дополнительные требования к монтажу силового кабеля. " * 20
    ).encode("utf-8")
    second_ingest = client.post(
        "/v1/ingest/document",
        headers=headers,
        data={
            "collection_id": "api:docs",
            "canonical_uri": "external-document://cable-2",
            "pre_chunked": "true",
        },
        files={"file": ("cable-2.txt", second_content, "text/plain")},
    )
    assert second_ingest.status_code == 200

    original_provider = app.state.platform_service.embedding_provider

    class FailingEmbeddingProvider:
        provider_name = original_provider.provider_name
        model_name = original_provider.model_name
        dimension = original_provider.dimension

        def embed_texts(self, texts):
            raise RuntimeError("synthetic embedding failure")

        def embed_query(self, text):
            raise RuntimeError("synthetic embedding failure")

    app.state.platform_service.embedding_provider = FailingEmbeddingProvider()
    failed_rebuild = client.post(
        "/v1/index/rebuild",
        headers=headers,
        json={"collection_id": "api:docs"},
    )
    assert failed_rebuild.status_code == 500
    app.state.platform_service.embedding_provider = original_provider

    stats_after_failure = client.get(
        "/v1/collections/api:docs/stats",
        headers=headers,
    )
    assert stats_after_failure.status_code == 200
    assert stats_after_failure.json()["active_index_revision"] == job["revision"]

    jobs_after_failure = app.state.platform_service.list_index_jobs(
        collection_id="api:docs"
    )
    assert jobs_after_failure[0]["status"] == "failed"
    assert jobs_after_failure[0]["revision"] != job["revision"]
    assert jobs_after_failure[0]["metrics"]["error_type"] == "RuntimeError"
    failed_run_id = jobs_after_failure[0]["run_id"]

    class FlakyEmbeddingProvider:
        provider_name = original_provider.provider_name
        model_name = original_provider.model_name
        dimension = original_provider.dimension

        def __init__(self):
            self.calls = 0

        def embed_texts(self, texts):
            self.calls += 1
            if self.calls < 3:
                raise EmbeddingServerUnavailableError("synthetic transient outage")
            return original_provider.embed_texts(texts)

        def embed_query(self, text):
            return original_provider.embed_query(text)

    flaky_provider = FlakyEmbeddingProvider()
    app.state.platform_service.embedding_provider = flaky_provider
    recovered_rebuild = client.post(
        "/v1/index/rebuild",
        headers=headers,
        json={"collection_id": "api:docs"},
    )
    assert recovered_rebuild.status_code == 200
    recovered_job = recovered_rebuild.json()
    assert recovered_job["run_id"] == failed_run_id
    assert recovered_job["status"] == "completed"
    assert recovered_job["metrics"]["embedding_attempts"] == 3
    assert flaky_provider.calls == 3
    recovered_revision = recovered_job["revision"]

    stats_after_recovery = client.get(
        "/v1/collections/api:docs/stats",
        headers=headers,
    )
    assert stats_after_recovery.status_code == 200
    assert stats_after_recovery.json()["active_index_revision"] == recovered_revision

    app.state.platform_service.embedding_provider = original_provider
    third_content = (
        "Третий документ меняет ревизию индекса и проверяет dead letter. " * 20
    ).encode("utf-8")
    third_ingest = client.post(
        "/v1/ingest/document",
        headers=headers,
        data={
            "collection_id": "api:docs",
            "canonical_uri": "external-document://cable-3",
            "pre_chunked": "true",
        },
        files={"file": ("cable-3.txt", third_content, "text/plain")},
    )
    assert third_ingest.status_code == 200

    class UnavailableEmbeddingProvider:
        provider_name = original_provider.provider_name
        model_name = original_provider.model_name
        dimension = original_provider.dimension

        def __init__(self):
            self.calls = 0

        def embed_texts(self, texts):
            self.calls += 1
            raise EmbeddingServerUnavailableError("synthetic persistent outage")

        def embed_query(self, text):
            raise EmbeddingServerUnavailableError("synthetic persistent outage")

    unavailable_provider = UnavailableEmbeddingProvider()
    app.state.platform_service.embedding_provider = unavailable_provider
    dead_letter_response = client.post(
        "/v1/index/rebuild",
        headers=headers,
        json={"collection_id": "api:docs"},
    )
    assert dead_letter_response.status_code == 500
    assert unavailable_provider.calls == 3

    jobs_after_dead_letter = app.state.platform_service.list_index_jobs(
        collection_id="api:docs"
    )
    dead_letter_job = next(
        item for item in jobs_after_dead_letter if item["status"] == "dead_letter"
    )
    assert dead_letter_job["metrics"]["error_type"] == "EmbeddingServerUnavailableError"
    assert dead_letter_job["metrics"]["embedding_attempts"] == 3
    assert dead_letter_job["metrics"]["dead_letter"] is True

    stats_after_dead_letter = client.get(
        "/v1/collections/api:docs/stats",
        headers=headers,
    )
    assert stats_after_dead_letter.status_code == 200
    assert (
        stats_after_dead_letter.json()["active_index_revision"]
        == recovered_revision
    )

    app.state.platform_service.embedding_provider = original_provider
    replayed_dead_letter = client.post(
        "/v1/index/rebuild",
        headers=headers,
        json={"collection_id": "api:docs"},
    )
    assert replayed_dead_letter.status_code == 200
    replayed_job = replayed_dead_letter.json()
    assert replayed_job["run_id"] == dead_letter_job["run_id"]
    assert replayed_job["revision"] == dead_letter_job["revision"]
    assert replayed_job["status"] == "completed"
    assert replayed_job["metrics"]["embedding_attempts"] == 1

    missing_scope = client.post(
        "/v1/search",
        headers=headers,
        json={
            "query": "силовой кабель",
            "collections": ["api:missing"],
        },
    )
    assert missing_scope.status_code == 404


def test_entity_resolution_is_ambiguity_safe() -> None:
    import uuid

    database_url = _database_url()
    os.environ["ARVECTUM_DATA_DATABASE_URL"] = database_url
    command.upgrade(Config("alembic.ini"), "head")

    app = create_app(
        Settings(
            environment="test",
            log_level="WARNING",
            database_url=database_url,
            internal_api_key="test-secret",
            embedding_provider="hashing",
            embedding_model="api-test-hash",
            embedding_dimension=64,
        )
    )
    client = TestClient(app)
    headers = {"X-Arvectum-Key": "test-secret"}

    suffix = uuid.uuid4().hex[:8]
    collection_id = f"entity:test:{suffix}"
    entity_type = f"supplier-test-{suffix}"

    created_collection = client.post(
        "/v1/collections",
        headers=headers,
        json={
            "collection_id": collection_id,
            "owner": "tests",
            "name": f"Entity test {suffix}",
            "default_language": "russian",
        },
    )
    assert created_collection.status_code == 200

    first_entity = client.post(
        "/v1/entities",
        headers=headers,
        json={
            "entity_type": entity_type,
            "canonical_name": "ООО Ромашка",
            "aliases": [
                {
                    "alias_kind": "identifier",
                    "value": "7701000001",
                    "source_collection_id": collection_id,
                    "metadata": {"scheme": "inn"},
                }
            ],
        },
    )
    assert first_entity.status_code == 200
    first_entity_id = first_entity.json()["entity_id"]

    second_entity = client.post(
        "/v1/entities",
        headers=headers,
        json={
            "entity_type": entity_type,
            "canonical_name": "ООО Ромашка",
            "aliases": [
                {
                    "alias_kind": "identifier",
                    "value": "7701000002",
                    "source_collection_id": collection_id,
                    "metadata": {"scheme": "inn"},
                }
            ],
        },
    )
    assert second_entity.status_code == 200
    second_entity_id = second_entity.json()["entity_id"]
    assert second_entity_id != first_entity_id

    ambiguous_name = client.post(
        "/v1/entities/resolve",
        headers=headers,
        json={
            "entity_type": entity_type,
            "value": "  ООО   РОМАШКА  ",
            "alias_kind": "name",
        },
    )
    assert ambiguous_name.status_code == 200
    assert ambiguous_name.json()["status"] == "ambiguous"
    assert {
        item["entity_id"] for item in ambiguous_name.json()["candidates"]
    } == {first_entity_id, second_entity_id}

    resolved_identifier = client.post(
        "/v1/entities/resolve",
        headers=headers,
        json={
            "entity_type": entity_type,
            "value": "7701000001",
            "alias_kind": "identifier",
        },
    )
    assert resolved_identifier.status_code == 200
    assert resolved_identifier.json()["status"] == "resolved"
    assert resolved_identifier.json()["candidates"][0]["entity_id"] == first_entity_id

    unresolved_identifier = client.post(
        "/v1/entities/resolve",
        headers=headers,
        json={
            "entity_type": entity_type,
            "value": "9999999999",
            "alias_kind": "identifier",
        },
    )
    assert unresolved_identifier.status_code == 200
    assert unresolved_identifier.json()["status"] == "unresolved"
    assert unresolved_identifier.json()["candidates"] == []

    fetched_entity = client.get(
        f"/v1/entities/{first_entity_id}",
        headers=headers,
    )
    assert fetched_entity.status_code == 200
    aliases = fetched_entity.json()["aliases"]
    assert any(alias["alias_kind"] == "name" for alias in aliases)
    assert any(
        alias["alias_kind"] == "identifier"
        and alias["value"] == "7701000001"
        for alias in aliases
    )

def test_entity_relations_are_idempotent_and_provenance_checked() -> None:
    database_url = _database_url()
    os.environ["ARVECTUM_DATA_DATABASE_URL"] = database_url
    command.upgrade(Config("alembic.ini"), "head")

    app = create_app(
        Settings(
            environment="test",
            log_level="WARNING",
            database_url=database_url,
            internal_api_key="test-secret",
            embedding_provider="hashing",
            embedding_model="entity-relation-test-hash",
            embedding_dimension=32,
        )
    )
    client = TestClient(app)
    headers = {"X-Arvectum-Key": "test-secret"}

    suffix = uuid.uuid4().hex[:8]
    collection_id = f"relations:test:{suffix}"
    created_collection = client.post(
        "/v1/collections",
        headers=headers,
        json={
            "collection_id": collection_id,
            "owner": "tests",
            "name": f"Relation test {suffix}",
            "default_language": "russian",
        },
    )
    assert created_collection.status_code == 200

    ingested = client.post(
        "/v1/ingest/document",
        headers=headers,
        data={
            "collection_id": collection_id,
            "canonical_uri": f"external-document://relations-{suffix}",
            "pre_chunked": "true",
        },
        files={
            "file": (
                "relation.txt",
                "ООО Ромашка поставляет кабель на объект.".encode("utf-8"),
                "text/plain",
            )
        },
    )
    assert ingested.status_code == 200

    searched = client.post(
        "/v1/search",
        headers=headers,
        json={
            "query": "поставляет кабель",
            "collections": [collection_id],
            "mode": "hybrid",
            "limit": 1,
        },
    )
    assert searched.status_code == 200
    hit = searched.json()["hits"][0]

    source_entity = client.post(
        "/v1/entities",
        headers=headers,
        json={
            "entity_type": f"supplier-{suffix}",
            "canonical_name": "ООО Ромашка",
        },
    )
    assert source_entity.status_code == 200

    target_entity = client.post(
        "/v1/entities",
        headers=headers,
        json={
            "entity_type": f"product-{suffix}",
            "canonical_name": "Кабель ВВГнг",
        },
    )
    assert target_entity.status_code == 200

    relation_payload = {
        "source_entity_id": source_entity.json()["entity_id"],
        "target_entity_id": target_entity.json()["entity_id"],
        "relation_type": "supplies",
        "source_collection_id": collection_id,
        "resource_id": hit["resource_id"],
        "document_id": hit["document_id"],
        "chunk_id": hit["chunk_id"],
        "metadata": {"source": "postgres-integration"},
    }

    created_relation = client.post(
        "/v1/entity-relations",
        headers=headers,
        json=relation_payload,
    )
    assert created_relation.status_code == 200
    relation = created_relation.json()
    assert relation["source_collection_id"] == collection_id
    assert relation["chunk_id"] == hit["chunk_id"]

    repeated_relation = client.post(
        "/v1/entity-relations",
        headers=headers,
        json=relation_payload,
    )
    assert repeated_relation.status_code == 200
    assert repeated_relation.json()["relation_id"] == relation["relation_id"]

    outbound = client.get(
        f"/v1/entities/{source_entity.json()['entity_id']}/relations"
        "?direction=outbound&relation_type=supplies",
        headers=headers,
    )
    assert outbound.status_code == 200
    assert [item["relation_id"] for item in outbound.json()] == [
        relation["relation_id"]
    ]

    inbound = client.get(
        f"/v1/entities/{target_entity.json()['entity_id']}/relations"
        "?direction=inbound&relation_type=supplies",
        headers=headers,
    )
    assert inbound.status_code == 200
    assert [item["relation_id"] for item in inbound.json()] == [
        relation["relation_id"]
    ]

    mismatched = dict(relation_payload)
    mismatched["document_id"] = "not-the-document"
    invalid_relation = client.post(
        "/v1/entity-relations",
        headers=headers,
        json=mismatched,
    )
    assert invalid_relation.status_code == 400

def test_federated_search_deduplicates_same_canonical_uri_across_collections() -> None:
    database_url = _database_url()
    os.environ["ARVECTUM_DATA_DATABASE_URL"] = database_url
    command.upgrade(Config("alembic.ini"), "head")

    app = create_app(
        Settings(
            environment="test",
            log_level="WARNING",
            database_url=database_url,
            internal_api_key="test-secret",
            consumer_api_keys={"growth-agent": "growth-secret"},
            embedding_provider="hashing",
            embedding_model="federated-dedup-test-hash",
            embedding_dimension=32,
        )
    )
    client = TestClient(app)
    headers = {"X-Arvectum-Key": "test-secret"}
    federation_headers = {
        **headers,
        "X-Arvectum-Consumer": "growth-agent",
        "X-Arvectum-Consumer-Key": "growth-secret",
    }

    for collection_id in ("dedup:site", "dedup:products"):
        created = client.post(
            "/v1/collections",
            headers=headers,
            json={
                "collection_id": collection_id,
                "owner": "tests",
                "name": collection_id,
                "default_language": "russian",
            },
        )
        assert created.status_code == 200

    shared_uri = "https://example.com/photo-size"
    for collection_id, text_value in (
        ("dedup:site", "Фото под размер. Изменение размера изображения."),
        ("dedup:products", "Фото под размер — продукт для iPhone."),
    ):
        ingested = client.post(
            "/v1/ingest/document",
            headers=headers,
            data={
                "collection_id": collection_id,
                "canonical_uri": shared_uri,
                "pre_chunked": "true",
            },
            files={
                "file": (
                    "photo-size.txt",
                    text_value.encode("utf-8"),
                    "text/plain",
                )
            },
        )
        assert ingested.status_code == 200

    extra = client.post(
        "/v1/ingest/document",
        headers=headers,
        data={
            "collection_id": "dedup:site",
            "canonical_uri": "https://example.com/other",
            "pre_chunked": "true",
        },
        files={
            "file": (
                "other.txt",
                "Другой инструмент для обработки фото.".encode("utf-8"),
                "text/plain",
            )
        },
    )
    assert extra.status_code == 200

    response = client.post(
        "/v1/search",
        headers=federation_headers,
        json={
            "query": "Фото под размер",
            "collections": ["dedup:site", "dedup:products"],
            "mode": "hybrid",
            "limit": 3,
        },
    )
    assert response.status_code == 200
    hits = response.json()["hits"]
    assert [hit["canonical_uri"] for hit in hits].count(shared_uri) == 1
    assert len(hits) == 2
    assert {hit["canonical_uri"] for hit in hits} == {
        shared_uri,
        "https://example.com/other",
    }


def test_embedding_model_migration_is_staged_and_activated_atomically() -> None:
    database_url = _database_url()
    os.environ["ARVECTUM_DATA_DATABASE_URL"] = database_url
    command.upgrade(Config("alembic.ini"), "head")

    first_provider = HashingEmbeddingProvider(
        model_name="migration-v1",
        dimension=32,
    )
    app = create_app(
        Settings(
            environment="test",
            log_level="WARNING",
            database_url=database_url,
            internal_api_key="test-secret",
            embedding_provider="hashing",
            embedding_model="migration-v1",
            embedding_dimension=32,
        ),
        platform_service=DataPlatformService(
            Settings(
                environment="test",
                log_level="WARNING",
                database_url=database_url,
                internal_api_key="test-secret",
                embedding_provider="hashing",
                embedding_model="migration-v1",
                embedding_dimension=32,
            ),
            embedding_provider=first_provider,
        ),
    )
    client = TestClient(app)
    headers = {"X-Arvectum-Key": "test-secret"}
    collection_id = f"migration:test:{uuid.uuid4().hex[:8]}"

    created = client.post(
        "/v1/collections",
        headers=headers,
        json={
            "collection_id": collection_id,
            "owner": "tests",
            "name": collection_id,
            "default_language": "russian",
        },
    )
    assert created.status_code == 200

    ingested = client.post(
        "/v1/ingest/document",
        headers=headers,
        data={
            "collection_id": collection_id,
            "canonical_uri": f"external-document://{collection_id}",
            "pre_chunked": "true",
        },
        files={
            "file": (
                "migration.txt",
                "Безопасная миграция эмбеддингов без частичного переключения.".encode("utf-8"),
                "text/plain",
            )
        },
    )
    assert ingested.status_code == 200

    service = app.state.platform_service

    class FailingMigrationProvider:
        provider_name = "hashing"
        model_name = "migration-v2"
        dimension = 48

        def embed_texts(self, texts):
            raise RuntimeError("synthetic migration failure")

        def embed_query(self, text):
            raise RuntimeError("synthetic migration failure")

    service.embedding_provider = FailingMigrationProvider()

    failed_migration = client.post(
        "/v1/index/rebuild",
        headers=headers,
        json={"collection_id": collection_id},
    )
    assert failed_migration.status_code == 500

    unchanged = client.get(f"/v1/collections/{collection_id}", headers=headers)
    assert unchanged.status_code == 200
    assert unchanged.json()["embedding_model"] == "migration-v1"
    assert unchanged.json()["embedding_dimension"] == 32

    service.embedding_provider = HashingEmbeddingProvider(
        model_name="migration-v2",
        dimension=48,
    )

    blocked_search = client.post(
        "/v1/search",
        headers=headers,
        json={
            "query": "миграция эмбеддингов",
            "collections": [collection_id],
            "mode": "vector",
        },
    )
    assert blocked_search.status_code == 400

    blocked_collection_update = client.post(
        "/v1/collections",
        headers=headers,
        json={
            "collection_id": collection_id,
            "owner": "tests",
            "name": collection_id,
            "default_language": "russian",
        },
    )
    assert blocked_collection_update.status_code == 400

    rebuilt = client.post(
        "/v1/index/rebuild",
        headers=headers,
        json={"collection_id": collection_id},
    )
    assert rebuilt.status_code == 200
    job = rebuilt.json()
    assert job["status"] == "completed"
    assert job["metrics"]["embedding_migration"] is True
    assert job["metrics"]["embedding_model"] == "migration-v2"
    assert job["metrics"]["embedding_dimension"] == 48

    fetched = client.get(f"/v1/collections/{collection_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["embedding_model"] == "migration-v2"
    assert fetched.json()["embedding_dimension"] == 48
    assert fetched.json()["active_index_revision"] == job["revision"]

    migrated_search = client.post(
        "/v1/search",
        headers=headers,
        json={
            "query": "миграция эмбеддингов",
            "collections": [collection_id],
            "mode": "vector",
        },
    )
    assert migrated_search.status_code == 200
    assert migrated_search.json()["hits"]
