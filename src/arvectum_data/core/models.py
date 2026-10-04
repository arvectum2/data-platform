from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class Resource:
    resource_id: str
    collection_id: str
    source_type: str
    canonical_uri: str
    content_hash: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Document:
    document_id: str
    resource_id: str
    title: str
    text: str
    content_hash: str
    media_type: str
    extraction_status: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Provenance:
    resource_id: str
    document_id: str
    canonical_uri: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class Chunk:
    chunk_id: str
    document_id: str
    ordinal: int
    text: str
    content_hash: str
    char_start: int
    char_end: int
    token_estimate: int
    provenance: Provenance
    metadata: Mapping[str, Any] = field(default_factory=dict)
