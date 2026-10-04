from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from ..search import SearchMode


class CollectionCreateRequest(BaseModel):
    collection_id: str = Field(min_length=1, max_length=128)
    owner: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    default_language: str = Field(default="simple", max_length=32)


CollectionCreate = CollectionCreateRequest


class CollectionResponse(BaseModel):
    collection_id: str
    owner: str
    name: str
    default_language: str
    embedding_provider: str | None = None
    embedding_model: str | None = None
    embedding_dimension: int | None = None
    active_index_revision: str | None = None


class CollectionStatsResponse(BaseModel):
    collection_id: str
    resources: int
    documents: int
    chunks: int
    embeddings: int


class UrlIngestRequest(BaseModel):
    collection_id: str = Field(min_length=1, max_length=128)
    url: str = Field(min_length=1, max_length=4096)
    title: str | None = None


URLIngestRequest = UrlIngestRequest


class IngestResponse(BaseModel):
    resource_id: str
    document_id: str
    collection_id: str
    chunks: int = 0
    chunks_indexed: int | None = None
    embeddings: int = 0
    canonical_uri: str | None = None
    extraction_status: str = "unknown"


class FieldSpecRequest(BaseModel):
    key: str = Field(min_length=1)
    required: bool = False
    min_confidence: float = Field(default=0.80, ge=0.0, le=1.0)
    min_margin: float = Field(default=0.10, ge=0.0, le=1.0)
    aliases: list[str] = Field(default_factory=list)


class ExtractRequest(BaseModel):
    asset_id: str = "api-extract"
    url: str | None = None
    source_url: str | None = None
    text: str | None = None
    html: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    fields: list[FieldSpecRequest] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_source(self):
        if not self.url and not self.text and not self.html and not self.attributes:
            raise ValueError("one of url, text, html or attributes is required")
        return self


class ExtractDecisionResponse(BaseModel):
    status: str
    selected_value: Any | None = None
    selected_candidate_id: str | None = None
    reason: str | None = None


class ExtractResponse(BaseModel):
    values: dict[str, Any]
    requires_confirmation: bool
    unresolved_required_fields: list[str]
    decisions: dict[str, ExtractDecisionResponse] = Field(default_factory=dict)
    provider_errors: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    collections: list[str] = Field(min_length=1)
    filters: dict[str, list[str]] = Field(default_factory=dict)
    limit: int = Field(default=10, ge=1, le=100)
    mode: SearchMode = SearchMode.HYBRID


class SearchScoreResponse(BaseModel):
    lexical: float | None
    vector: float | None
    fusion: float


ScoreResponse = SearchScoreResponse


class SearchEvidenceResponse(BaseModel):
    resource_id: str
    document_id: str
    chunk_id: str
    canonical_uri: str


EvidenceResponse = SearchEvidenceResponse


class SearchHitResponse(BaseModel):
    chunk_id: str
    document_id: str
    resource_id: str
    canonical_uri: str
    title: str
    preview: str
    text: str | None = None
    scores: SearchScoreResponse
    evidence: list[SearchEvidenceResponse]
    metadata: dict[str, Any]


class SearchResponse(BaseModel):
    query: str | None = None
    hits: list[SearchHitResponse]


class StatusResponse(BaseModel):
    status: str
    database_configured: bool
    embedding_provider: str
    embedding_model: str
    embedding_dimension: int | None
    metrics: dict[str, int] = Field(default_factory=dict)
    requests: int = 0


class IndexRebuildRequest(BaseModel):
    collection_id: str = Field(min_length=1, max_length=128)


class IndexJobResponse(BaseModel):
    run_id: str
    collection_id: str
    run_type: str
    revision: str
    status: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    started_at: Any
    completed_at: Any | None = None


class ConnectorHealthResponse(BaseModel):
    name: str
    state: str
    capabilities: list[str]
    detail: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiscoveryRequest(BaseModel):
    connector: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1)
    cursor: str | None = None
    limit: int = Field(default=10, ge=1, le=200)


class DiscoveredResourceResponse(BaseModel):
    canonical_uri: str
    provider: str
    source_type: str
    external_id: str | None = None
    title: str | None = None
    snippet: str | None = None
    rank: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiscoveryResponse(BaseModel):
    resources: list[DiscoveredResourceResponse]
    next_cursor: str | None = None
    warnings: list[str] = Field(default_factory=list)
