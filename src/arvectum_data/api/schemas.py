from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from ..search import SearchMode


class ConsumerContractResponse(BaseModel):
    name: str
    version: str
    api_prefix: str = "/v1"
    capabilities: list[str]
    internal_api_key_header: str = "X-Arvectum-Key"
    consumer_id_header: str = "X-Arvectum-Consumer"
    consumer_key_header: str = "X-Arvectum-Consumer-Key"


class CollectionAccessPolicy(BaseModel):
    allowed_consumers: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_consumers(self):
        normalized = [item.strip() for item in self.allowed_consumers if item.strip()]
        if len(set(normalized)) != len(normalized):
            raise ValueError("allowed_consumers must be unique")
        self.allowed_consumers = normalized
        return self

class CollectionCreateRequest(BaseModel):
    collection_id: str = Field(min_length=1, max_length=128)
    owner: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    default_language: str = Field(default="simple", max_length=32)
    access_policy: CollectionAccessPolicy | None = None


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
    access_policy: dict[str, Any] = Field(default_factory=dict)


class CollectionStatsResponse(BaseModel):
    collection_id: str
    resources: int
    documents: int
    chunks: int
    embeddings: int
    first_seen_at: Any | None = None
    last_seen_at: Any | None = None
    latest_embedding_at: Any | None = None
    latest_reindex_completed_at: Any | None = None
    active_index_revision: str | None = None


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
    embeddings_written: int | None = None
    embeddings_skipped_existing: int = 0
    embedding_attempts: int = 0
    canonical_uri: str | None = None
    extraction_status: str = "unknown"


class ProcessedChunkResponse(BaseModel):
    chunk_id: str
    ordinal: int
    text: str
    content_hash: str
    char_start: int
    char_end: int
    token_estimate: int


class ProcessDocumentResponse(BaseModel):
    resource_id: str
    document_id: str
    collection_id: str
    canonical_uri: str
    title: str
    media_type: str
    extraction_status: str
    text: str
    chunks: list[ProcessedChunkResponse]


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
    lexical_weight: float = Field(default=1.0, ge=0.0, le=20.0)
    vector_weight: float = Field(default=1.0, ge=0.0, le=20.0)
    query_variants: list[str] = Field(default_factory=list, max_length=8)
    query_variant_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    expand_query: bool = False
    query_expansion_limit: int = Field(default=4, ge=1, le=8)
    collapse_by_canonical_uri: bool = False
    rerank: bool = False
    rerank_candidates: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def normalize_query_variants(self):
        seen = {self.query.strip()}
        normalized: list[str] = []
        for variant in self.query_variants:
            cleaned = variant.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)
        self.query_variants = normalized
        if self.rerank and self.rerank_candidates < self.limit:
            raise ValueError("rerank_candidates must be greater than or equal to limit")
        return self


class SearchScoreResponse(BaseModel):
    lexical: float | None
    vector: float | None
    fusion: float
    rerank: float | None = None


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


class QueryExpansionResponse(BaseModel):
    text: str
    source: str
    weight: float


class SearchResponse(BaseModel):
    query: str | None = None
    hits: list[SearchHitResponse]
    query_expansions: list[QueryExpansionResponse] = Field(default_factory=list)


class StatusResponse(BaseModel):
    status: str
    database_configured: bool
    embedding_provider: str
    embedding_model: str
    embedding_dimension: int | None
    ocr_provider: str | None = None
    model_roles: dict[str, dict[str, Any]] = Field(default_factory=dict)
    metrics: dict[str, int] = Field(default_factory=dict)
    requests: int = 0
    operations: dict[str, dict[str, int]] = Field(default_factory=dict)


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


class RelevanceFeedbackRequest(BaseModel):
    collection_id: str = Field(min_length=1, max_length=128)
    resource_id: str = Field(min_length=1, max_length=64)
    document_id: str = Field(min_length=1, max_length=64)
    chunk_id: str = Field(min_length=1, max_length=64)
    query: str = Field(min_length=1, max_length=4096)
    label: str
    rank: int | None = Field(default=None, ge=1, le=1000)
    actor: str | None = Field(default=None, max_length=128)
    context: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_feedback(self):
        allowed = {"relevant", "partially_relevant", "not_relevant"}
        if self.label not in allowed:
            raise ValueError(
                "label must be relevant, partially_relevant or not_relevant"
            )
        if len(self.context) > 20:
            raise ValueError("feedback context may contain at most 20 keys")
        return self


class RelevanceFeedbackResponse(BaseModel):
    feedback_id: str
    collection_id: str
    resource_id: str
    document_id: str
    chunk_id: str
    query_hash: str
    label: str
    rank: int | None = None
    actor: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    created_at: Any


class RelevanceFeedbackSummaryResponse(BaseModel):
    collection_id: str
    total: int
    relevant: int
    partially_relevant: int
    not_relevant: int


class EntityAliasRequest(BaseModel):
    alias_kind: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=4096)
    source_collection_id: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EntityAliasResponse(BaseModel):
    alias_id: str
    alias_kind: str
    value: str
    normalized_value: str
    source_collection_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: Any


class EntityCreateRequest(BaseModel):
    entity_type: str = Field(min_length=1, max_length=128)
    canonical_name: str = Field(min_length=1, max_length=4096)
    aliases: list[EntityAliasRequest] = Field(default_factory=list, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EntityResponse(BaseModel):
    entity_id: str
    entity_type: str
    canonical_name: str
    aliases: list[EntityAliasResponse] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: Any
    updated_at: Any


class EntityResolveRequest(BaseModel):
    entity_type: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1, max_length=4096)
    alias_kind: str = Field(default="name", min_length=1, max_length=64)
    limit: int = Field(default=20, ge=1, le=100)


class EntityResolveResponse(BaseModel):
    status: str
    normalized_value: str
    candidates: list[EntityResponse] = Field(default_factory=list)


class EntityRelationCreateRequest(BaseModel):
    source_entity_id: str = Field(min_length=1, max_length=36)
    target_entity_id: str = Field(min_length=1, max_length=36)
    relation_type: str = Field(min_length=1, max_length=128)
    source_collection_id: str | None = Field(default=None, max_length=128)
    resource_id: str | None = Field(default=None, max_length=64)
    document_id: str | None = Field(default=None, max_length=64)
    chunk_id: str | None = Field(default=None, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EntityRelationResponse(BaseModel):
    relation_id: str
    source_entity_id: str
    target_entity_id: str
    relation_type: str
    source_collection_id: str | None = None
    resource_id: str | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: Any
