from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping, Sequence

from .models import GenerationRequest, TextGenerationProvider
from .search import SearchHit


@dataclass(frozen=True, slots=True)
class AliasSuggestion:
    entity_id: str
    alias: str
    chunk_id: str


@dataclass(frozen=True, slots=True)
class RelationSuggestion:
    source_entity_id: str
    target_entity_id: str
    relation_type: str
    chunk_id: str
    valid_from: str | None = None
    valid_to: str | None = None


@dataclass(frozen=True, slots=True)
class GraphSuggestions:
    aliases: tuple[AliasSuggestion, ...]
    relations: tuple[RelationSuggestion, ...]


class EvidenceGraphSuggester:
    """Suggest graph enrichment without mutating canonical graph state."""

    def __init__(self, provider: TextGenerationProvider, *, max_hits: int = 12) -> None:
        self.provider = provider
        self.max_hits = max_hits

    def suggest(
        self,
        *,
        entities: Sequence[Mapping[str, object]],
        hits: Sequence[SearchHit],
    ) -> GraphSuggestions:
        bounded = tuple(hits[: self.max_hits])
        allowed_chunks = {hit.chunk_id for hit in bounded}
        allowed_entities = {str(entity["entity_id"]) for entity in entities}
        if not bounded or not allowed_entities:
            return GraphSuggestions((), ())
        context = {
            "entities": [
                {
                    "entity_id": str(entity["entity_id"]),
                    "entity_type": entity.get("entity_type"),
                    "canonical_name": entity.get("canonical_name"),
                }
                for entity in entities
            ],
            "evidence": [
                {"chunk_id": hit.chunk_id, "text": hit.text[:2400]}
                for hit in bounded
            ],
        }
        response = self.provider.generate(
            GenerationRequest(
                system_prompt=(
                    "Suggest aliases and entity relations ONLY when explicitly supported by "
                    "the supplied evidence. Use only supplied entity_id and chunk_id values. "
                    "Do not infer missing relations. Return strict JSON only."
                ),
                prompt=json.dumps(context, ensure_ascii=False)
                + '\nReturn {"aliases":[{"entity_id","alias","chunk_id"}],'
                '"relations":[{"source_entity_id","target_entity_id","relation_type",'
                '"chunk_id","valid_from","valid_to"}]}.',
                max_tokens=2048,
                temperature=0.0,
                metadata={"operation": "graph-suggestions"},
            )
        )
        payload = json.loads(response.text)
        aliases: list[AliasSuggestion] = []
        for item in payload.get("aliases", []):
            entity_id = str(item.get("entity_id", ""))
            chunk_id = str(item.get("chunk_id", ""))
            alias = str(item.get("alias", "")).strip()
            if entity_id in allowed_entities and chunk_id in allowed_chunks and alias:
                aliases.append(AliasSuggestion(entity_id, alias, chunk_id))
        relations: list[RelationSuggestion] = []
        for item in payload.get("relations", []):
            source = str(item.get("source_entity_id", ""))
            target = str(item.get("target_entity_id", ""))
            chunk_id = str(item.get("chunk_id", ""))
            relation_type = str(item.get("relation_type", "")).strip()
            if (
                source in allowed_entities
                and target in allowed_entities
                and source != target
                and chunk_id in allowed_chunks
                and relation_type
            ):
                relations.append(
                    RelationSuggestion(
                        source,
                        target,
                        relation_type,
                        chunk_id,
                        item.get("valid_from"),
                        item.get("valid_to"),
                    )
                )
        return GraphSuggestions(tuple(aliases), tuple(relations))
