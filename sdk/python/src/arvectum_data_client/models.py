from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class ConsumerContract(TypedDict):
    name: str
    version: str
    api_prefix: str
    capabilities: list[str]
    internal_api_key_header: str
    consumer_id_header: str
    consumer_key_header: str


class Collection(TypedDict, total=False):
    collection_id: str
    owner: str
    name: str
    default_language: str
    embedding_provider: str | None
    embedding_model: str | None
    embedding_dimension: int | None
    active_index_revision: str | None
    access_policy: dict[str, Any]


class CollectionStats(TypedDict, total=False):
    collection_id: str
    resources: int
    documents: int
    chunks: int
    embeddings: int
    first_seen_at: Any | None
    last_seen_at: Any | None
    latest_embedding_at: Any | None
    latest_reindex_completed_at: Any | None
    active_index_revision: str | None


class IngestResult(TypedDict, total=False):
    resource_id: str
    document_id: str
    collection_id: str
    chunks: int
    chunks_indexed: int | None
    embeddings: int
    embeddings_written: int | None
    embeddings_skipped_existing: int
    embedding_attempts: int
    canonical_uri: str | None
    extraction_status: str


class ProcessedChunk(TypedDict):
    chunk_id: str
    ordinal: int
    text: str
    content_hash: str
    char_start: int
    char_end: int
    token_estimate: int


class ProcessedDocument(TypedDict):
    resource_id: str
    document_id: str
    collection_id: str
    canonical_uri: str
    title: str
    media_type: str
    extraction_status: str
    text: str
    chunks: list[ProcessedChunk]


class SearchScores(TypedDict):
    lexical: float | None
    vector: float | None
    fusion: float


class SearchEvidence(TypedDict):
    resource_id: str
    document_id: str
    chunk_id: str
    canonical_uri: str


class SearchHit(TypedDict):
    chunk_id: str
    document_id: str
    resource_id: str
    canonical_uri: str
    title: str
    preview: str
    text: str | None
    scores: SearchScores
    evidence: list[SearchEvidence]
    metadata: dict[str, Any]


class SearchResponse(TypedDict):
    query: str | None
    hits: list[SearchHit]


class DiscoveredResource(TypedDict, total=False):
    canonical_uri: str
    provider: str
    source_type: str
    external_id: str | None
    title: str | None
    snippet: str | None
    rank: int | None
    metadata: dict[str, Any]


class DiscoveryResponse(TypedDict):
    resources: list[DiscoveredResource]
    next_cursor: str | None
    warnings: list[str]


class EntityAlias(TypedDict, total=False):
    alias_id: str
    alias_kind: str
    value: str
    normalized_value: str
    source_collection_id: str | None
    metadata: dict[str, Any]
    created_at: Any


class Entity(TypedDict, total=False):
    entity_id: str
    entity_type: str
    canonical_name: str
    aliases: list[EntityAlias]
    metadata: dict[str, Any]
    created_at: Any
    updated_at: Any


class EntityResolveResponse(TypedDict):
    status: str
    normalized_value: str
    candidates: list[Entity]


class EntityRelation(TypedDict, total=False):
    relation_id: str
    source_entity_id: str
    target_entity_id: str
    relation_type: str
    source_collection_id: str | None
    resource_id: str | None
    document_id: str | None
    chunk_id: str | None
    metadata: dict[str, Any]
    created_at: Any


class EntityAliasInput(TypedDict):
    alias_kind: str
    value: str
    source_collection_id: NotRequired[str | None]
    metadata: NotRequired[dict[str, Any]]
