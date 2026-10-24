"""Generic terminology API: authenticated search request is passed into core."""

from __future__ import annotations

from fastapi.testclient import TestClient

from arvectum_data.api.app import create_app
from arvectum_data.api.config import Settings
from arvectum_data.search import SearchEvidence, SearchHit, SearchScores


class Platform:
    def __init__(self):
        self.seen = []

    def search(self, query, *, consumer=None):
        self.seen.append((query, consumer))
        return [
            SearchHit(
                chunk_id="equipment-1", document_id="project-1",
                resource_id="archive-1",
                canonical_uri="https://example.org/original/project-1.xml",
                title="Строительство распределительного узла",
                preview="в составе поставки — СТАТКОМ",
                text="Поставка в составе EPC: СТАТКОМ, 20 МВАр",
                scores=SearchScores(lexical=0.7, vector=0.8, fusion=0.75),
                evidence=(SearchEvidence(
                    chunk_id="equipment-1", document_id="project-1",
                    resource_id="archive-1",
                    canonical_uri="https://example.org/original/project-1.xml",
                ),),
                metadata={"terminology_matches": [
                    {"id": "pq_statcom", "terms": ["СТАТКОМ"],
                     "contexts": [], "classification": "explicit_technical_candidate"},
                ]},
            )
        ]


def _client(service):
    return TestClient(create_app(
        Settings(
            environment="test", internal_api_key="operator-test-secret",
            consumer_api_keys={"consumer": "consumer-test-secret"},
        ),
        platform_service=service,
    ))


def _payload():
    return {
        "query": "Техническая часть СТАТКОМ",
        "collections": ["tender:corpus"],
        "mode": "hybrid",
        "terminology_groups": [{
            "id": "pq_statcom",
            "aliases": ["СТАТКОМ", "STATCOM", "SVG"],
            "contexts": ["ПС 110 кВ", "реактивная мощность"],
            "exclusions": ["SVG vector graphics"],
            "ambiguous_aliases": ["SVG"],
        }],
        "terminology_expansion_limit": 2,
        "terminology_version": "power-quality-ontology/0.1",
    }


def test_http_accepts_domain_ontology_and_keeps_primary_source_metadata():
    svc = Platform()
    with _client(svc) as client:
        response = client.post(
            "/v1/search",
            json=_payload(),
            headers={
                "X-Arvectum-Consumer": "consumer",
                "X-Arvectum-Consumer-Key": "consumer-test-secret",
            },
        )
    assert response.status_code == 200, response.text
    query, consumer = svc.seen[0]
    assert consumer == "consumer"
    assert query.terminology_groups[0].id == "pq_statcom"
    assert query.terminology_groups[0].ambiguous_aliases == ("SVG",)
    assert query.terminology_expansion_limit == 2
    assert query.terminology_version == "power-quality-ontology/0.1"
    body = response.json()
    assert body["hits"][0]["metadata"]["terminology_matches"][0]["id"] == "pq_statcom"
    assert body["hits"][0]["evidence"][0]["chunk_id"] == "equipment-1"


def test_http_rejects_invalid_or_unbounded_ontology():
    svc = Platform()
    payload = _payload()
    payload["terminology_groups"][0]["ambiguous_aliases"] = ["unregistered"]
    with _client(svc) as client:
        response = client.post(
            "/v1/search", json=payload,
            headers={"X-Arvectum-Consumer": "consumer",
                     "X-Arvectum-Consumer-Key": "consumer-test-secret"},
        )
    assert response.status_code == 422
    assert not svc.seen


def test_http_multi_collection_cannot_bypass_auth_with_terminology():
    svc = Platform()
    payload = _payload()
    payload["collections"] = ["tenant:a", "tenant:b"]
    with _client(svc) as client:
        response = client.post("/v1/search", json=payload)
    assert response.status_code in (401, 403)
    assert svc.seen == []
