from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from .core.models import Chunk, Document, Provenance, Resource
from .documents.ingest import DocumentIngestResult
from .processing import ChunkingConfig, chunk_text


class MemoryKind(StrEnum):
    SOURCE_EVIDENCE = "source_evidence"
    AGENT_OBSERVATION = "agent_observation"
    USER_MEMORY = "user_memory"


class MemoryConflictPolicy(StrEnum):
    APPEND = "append"
    SUPERSEDE = "supersede"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class MemoryWrite:
    collection_id: str
    text: str
    kind: MemoryKind
    producer: str
    title: str = "Memory"
    source_chunk_ids: tuple[str, ...] = ()
    model_provider: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    subject_key: str | None = None
    conflict_policy: MemoryConflictPolicy = MemoryConflictPolicy.APPEND
    metadata: Mapping[str, object] | None = None


def build_memory_ingest(write: MemoryWrite, *, memory_id: str | None = None) -> DocumentIngestResult:
    if not write.text.strip():
        raise ValueError("memory text must not be blank")
    if not write.producer.strip():
        raise ValueError("memory producer must not be blank")
    resolved_id = memory_id or str(uuid.uuid4())
    canonical_uri = f"memory://{write.collection_id}/{resolved_id}"
    content_hash = hashlib.sha256(write.text.encode("utf-8")).hexdigest()
    resource_id = hashlib.sha256(
        f"resource\0{write.collection_id}\0memory\0{canonical_uri}".encode()
    ).hexdigest()
    document_id = hashlib.sha256(
        f"document\0{resource_id}\0{content_hash}".encode()
    ).hexdigest()
    metadata = {
        "memory_kind": write.kind.value,
        "producer": write.producer,
        "model_provider": write.model_provider,
        "model_name": write.model_name,
        "model_version": write.model_version,
        "subject_key": write.subject_key,
        **dict(write.metadata or {}),
    }
    resource = Resource(
        resource_id=resource_id,
        collection_id=write.collection_id,
        source_type="memory",
        canonical_uri=canonical_uri,
        content_hash=content_hash,
        metadata=metadata,
    )
    document = Document(
        document_id=document_id,
        resource_id=resource_id,
        title=write.title,
        text=write.text,
        content_hash=content_hash,
        media_type="text/plain",
        extraction_status="authored",
        metadata=metadata,
    )
    provenance = Provenance(
        resource_id=resource_id,
        document_id=document_id,
        canonical_uri=canonical_uri,
        content_hash=content_hash,
    )
    drafts = chunk_text(write.text, ChunkingConfig(min_chunk_chars=1))
    chunks = tuple(
        Chunk(
            chunk_id=hashlib.sha256(
                f"chunk\0{document_id}\0{draft.text_hash}\0{draft.chunk_index}".encode()
            ).hexdigest(),
            document_id=document_id,
            ordinal=draft.chunk_index,
            text=draft.text,
            content_hash=draft.text_hash,
            char_start=draft.char_start,
            char_end=draft.char_end,
            token_estimate=draft.token_estimate,
            provenance=provenance,
            metadata=metadata,
        )
        for draft in drafts
    )
    return DocumentIngestResult(resource=resource, document=document, chunks=chunks)
