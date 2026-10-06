from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select

from ...graph import EvidenceGraphSuggester, GraphSuggestions
from ...entities import normalize_entity_value
from ...models import ModelRole

from ...search import (
    SearchQuery,
)
from ...storage.postgres import (
    ChunkRow,
    CollectionRow,
    DocumentRow,
    EntityAliasRow,
    EntityRow,
    EntityRelationRow,
    ResourceRow,
    RelevanceFeedbackRow,
)

from ..service_support import (
    CollectionNotFound,
    EntityNotFound,
)


class GraphServiceMixin:
    @staticmethod
    def _entity_payload(entity: EntityRow) -> dict[str, Any]:
        aliases = sorted(
            entity.aliases,
            key=lambda item: (
                item.alias_kind,
                item.normalized_value,
                item.alias_id,
            ),
        )
        return {
            "entity_id": entity.entity_id,
            "entity_type": entity.entity_type,
            "canonical_name": entity.canonical_name,
            "aliases": [
                {
                    "alias_id": alias.alias_id,
                    "alias_kind": alias.alias_kind,
                    "value": alias.alias_value,
                    "normalized_value": alias.normalized_value,
                    "source_collection_id": alias.source_collection_id,
                    "metadata": dict(alias.metadata_json or {}),
                    "created_at": alias.created_at,
                }
                for alias in aliases
            ],
            "metadata": dict(entity.metadata_json or {}),
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
        }

    def create_entity(
        self,
        *,
        entity_type: str,
        canonical_name: str,
        aliases: Sequence[Mapping[str, object]] = (),
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        normalized_canonical = normalize_entity_value(canonical_name)
        if not normalized_canonical:
            raise ValueError("canonical entity name is empty after normalization")

        with self._require_factory()() as session:
            entity = EntityRow(
                entity_type=entity_type.strip(),
                canonical_name=canonical_name.strip(),
                metadata_json=dict(metadata or {}),
            )
            session.add(entity)
            session.flush()

            alias_specs: list[dict[str, object]] = [
                {
                    "alias_kind": "name",
                    "value": canonical_name,
                    "source_collection_id": None,
                    "metadata": {"canonical": True},
                }
            ]
            alias_specs.extend(dict(item) for item in aliases)

            seen: set[tuple[str, str]] = set()
            for spec in alias_specs:
                kind = str(spec.get("alias_kind") or "").strip()
                value = str(spec.get("value") or "").strip()
                normalized = normalize_entity_value(value)
                if not kind or not normalized:
                    raise ValueError("entity alias kind and value are required")
                identity = (kind, normalized)
                if identity in seen:
                    continue
                seen.add(identity)

                source_collection_id = spec.get("source_collection_id")
                if source_collection_id is not None:
                    source_collection_id = str(source_collection_id)
                    if session.get(CollectionRow, source_collection_id) is None:
                        raise CollectionNotFound(source_collection_id)

                session.add(
                    EntityAliasRow(
                        entity_id=entity.entity_id,
                        entity_type=entity.entity_type,
                        alias_kind=kind,
                        alias_value=value,
                        normalized_value=normalized,
                        source_collection_id=source_collection_id,
                        metadata_json=dict(spec.get("metadata") or {}),
                    )
                )

            session.commit()
            session.refresh(entity)
            _ = entity.aliases
            return self._entity_payload(entity)

    def get_entity(self, entity_id: str) -> dict[str, Any]:
        with self._require_factory()() as session:
            entity = session.get(EntityRow, entity_id)
            if entity is None:
                raise EntityNotFound(entity_id)
            _ = entity.aliases
            return self._entity_payload(entity)

    def resolve_entity(
        self,
        *,
        entity_type: str,
        value: str,
        alias_kind: str = "name",
        limit: int = 20,
    ) -> dict[str, Any]:
        normalized = normalize_entity_value(value)
        if not normalized:
            raise ValueError("entity value is empty after normalization")

        with self._require_factory()() as session:
            rows = (
                session.scalars(
                    select(EntityRow)
                    .join(
                        EntityAliasRow,
                        EntityAliasRow.entity_id == EntityRow.entity_id,
                    )
                    .where(
                        EntityAliasRow.entity_type == entity_type.strip(),
                        EntityAliasRow.alias_kind == alias_kind.strip(),
                        EntityAliasRow.normalized_value == normalized,
                    )
                    .order_by(
                        EntityRow.created_at.asc(),
                        EntityRow.entity_id.asc(),
                    )
                    .limit(max(1, min(limit, 100)))
                )
                .unique()
                .all()
            )
            for entity in rows:
                _ = entity.aliases
            status = "unresolved" if not rows else "resolved" if len(rows) == 1 else "ambiguous"
            return {
                "status": status,
                "normalized_value": normalized,
                "candidates": [self._entity_payload(entity) for entity in rows],
            }

    @staticmethod
    def _relation_payload(row: EntityRelationRow) -> dict[str, Any]:
        return {
            "relation_id": row.relation_id,
            "source_entity_id": row.source_entity_id,
            "target_entity_id": row.target_entity_id,
            "relation_type": row.relation_type,
            "status": row.status,
            "valid_from": row.valid_from,
            "valid_to": row.valid_to,
            "source_collection_id": row.source_collection_id,
            "resource_id": row.resource_id,
            "document_id": row.document_id,
            "chunk_id": row.chunk_id,
            "metadata": dict(row.metadata_json or {}),
            "created_at": row.created_at,
        }

    def create_entity_relation(
        self,
        *,
        source_entity_id: str,
        target_entity_id: str,
        relation_type: str,
        status: str = "canonical",
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        source_collection_id: str | None = None,
        resource_id: str | None = None,
        document_id: str | None = None,
        chunk_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        if source_entity_id == target_entity_id:
            raise ValueError("entity relation cannot target the same entity")
        normalized_type = relation_type.strip()
        if not normalized_type:
            raise ValueError("relation_type is required")
        normalized_status = status.strip().lower()
        if normalized_status not in {"canonical", "proposed", "rejected"}:
            raise ValueError("relation status must be canonical, proposed or rejected")
        if valid_from is not None and valid_to is not None and valid_to < valid_from:
            raise ValueError("valid_to must be greater than or equal to valid_from")
        if normalized_status == "proposed" and chunk_id is None:
            raise ValueError("proposed relations require chunk evidence")

        with self._require_factory()() as session:
            if session.get(EntityRow, source_entity_id) is None:
                raise EntityNotFound(source_entity_id)
            if session.get(EntityRow, target_entity_id) is None:
                raise EntityNotFound(target_entity_id)

            resolved_collection = source_collection_id
            resolved_resource = resource_id
            resolved_document = document_id
            resolved_chunk = chunk_id

            if resolved_chunk is not None:
                chunk = session.get(ChunkRow, resolved_chunk)
                if chunk is None:
                    raise ValueError("relation chunk does not exist")
                if resolved_document is not None and resolved_document != chunk.document_id:
                    raise ValueError("relation chunk/document mismatch")
                resolved_document = chunk.document_id

            if resolved_document is not None:
                document = session.get(DocumentRow, resolved_document)
                if document is None:
                    raise ValueError("relation document does not exist")
                if resolved_resource is not None and resolved_resource != document.resource_id:
                    raise ValueError("relation document/resource mismatch")
                resolved_resource = document.resource_id

            if resolved_resource is not None:
                resource = session.get(ResourceRow, resolved_resource)
                if resource is None:
                    raise ValueError("relation resource does not exist")
                if (
                    resolved_collection is not None
                    and resolved_collection != resource.collection_id
                ):
                    raise ValueError("relation resource/collection mismatch")
                resolved_collection = resource.collection_id
            elif resolved_collection is not None:
                if session.get(CollectionRow, resolved_collection) is None:
                    raise CollectionNotFound(resolved_collection)

            identity = "\n".join(
                [
                    source_entity_id,
                    target_entity_id,
                    normalized_type,
                    resolved_collection or "",
                    resolved_resource or "",
                    resolved_document or "",
                    resolved_chunk or "",
                ]
            )
            relation_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            existing = session.get(EntityRelationRow, relation_id)
            if existing is not None:
                return self._relation_payload(existing)

            row = EntityRelationRow(
                relation_id=relation_id,
                source_entity_id=source_entity_id,
                target_entity_id=target_entity_id,
                relation_type=normalized_type,
                status=normalized_status,
                valid_from=valid_from,
                valid_to=valid_to,
                source_collection_id=resolved_collection,
                resource_id=resolved_resource,
                document_id=resolved_document,
                chunk_id=resolved_chunk,
                metadata_json=dict(metadata or {}),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._relation_payload(row)

    def list_entity_relations(
        self,
        entity_id: str,
        *,
        direction: str = "both",
        relation_type: str | None = None,
        status: str | None = "canonical",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        normalized_direction = direction.strip().lower()
        if normalized_direction not in {"outbound", "inbound", "both"}:
            raise ValueError("direction must be outbound, inbound or both")

        with self._require_factory()() as session:
            if session.get(EntityRow, entity_id) is None:
                raise EntityNotFound(entity_id)

            statement = select(EntityRelationRow)
            if normalized_direction == "outbound":
                statement = statement.where(EntityRelationRow.source_entity_id == entity_id)
            elif normalized_direction == "inbound":
                statement = statement.where(EntityRelationRow.target_entity_id == entity_id)
            else:
                statement = statement.where(
                    or_(
                        EntityRelationRow.source_entity_id == entity_id,
                        EntityRelationRow.target_entity_id == entity_id,
                    )
                )
            if relation_type:
                statement = statement.where(
                    EntityRelationRow.relation_type == relation_type.strip()
                )
            if status is not None:
                normalized_status = status.strip().lower()
                if normalized_status not in {"canonical", "proposed", "rejected"}:
                    raise ValueError("relation status must be canonical, proposed or rejected")
                statement = statement.where(EntityRelationRow.status == normalized_status)
            statement = statement.order_by(
                EntityRelationRow.created_at.asc(),
                EntityRelationRow.relation_id.asc(),
            ).limit(max(1, min(limit, 500)))
            return [self._relation_payload(row) for row in session.scalars(statement).all()]

    def suggest_graph_enrichment(
        self,
        *,
        query: str,
        collection_id: str,
        entity_ids: Sequence[str],
        evidence_limit: int = 8,
        consumer: str | None = None,
    ) -> GraphSuggestions:
        provider = self.model_router.provider(ModelRole.REASONING)
        if provider is None:
            return GraphSuggestions((), ())
        entities = [self.get_entity(entity_id) for entity_id in dict.fromkeys(entity_ids)]
        hits = self.search(
            SearchQuery(
                query=query,
                collections=(collection_id,),
                limit=max(1, min(evidence_limit, 20)),
            ),
            consumer=consumer,
        )
        return EvidenceGraphSuggester(provider).suggest(entities=entities, hits=hits)

    def review_entity_relation(
        self,
        relation_id: str,
        *,
        decision: str,
        reviewer: str | None = None,
    ) -> dict[str, Any]:
        normalized = decision.strip().lower()
        if normalized not in {"canonical", "rejected"}:
            raise ValueError("review decision must be canonical or rejected")
        with self._require_factory()() as session:
            row = session.get(EntityRelationRow, relation_id)
            if row is None:
                raise LookupError(relation_id)
            if row.status != "proposed":
                raise ValueError("only proposed relations can be reviewed")
            row.status = normalized
            metadata = dict(row.metadata_json or {})
            metadata["review"] = {"decision": normalized, "reviewer": reviewer}
            row.metadata_json = metadata
            session.commit()
            session.refresh(row)
            return self._relation_payload(row)

    def traverse_entity_graph(
        self,
        entity_id: str,
        *,
        max_depth: int = 2,
        relation_type: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        if max_depth < 1 or max_depth > 5:
            raise ValueError("max_depth must be between 1 and 5")
        frontier = {entity_id}
        visited = {entity_id}
        result: list[dict[str, Any]] = []
        seen_relations: set[str] = set()
        for depth in range(1, max_depth + 1):
            next_frontier: set[str] = set()
            for current in sorted(frontier):
                rows = self.list_entity_relations(
                    current,
                    direction="both",
                    relation_type=relation_type,
                    status="canonical",
                    limit=min(limit, 500),
                )
                for row in rows:
                    if row["relation_id"] in seen_relations:
                        continue
                    seen_relations.add(row["relation_id"])
                    enriched = dict(row)
                    enriched["depth"] = depth
                    result.append(enriched)
                    if len(result) >= limit:
                        return result
                    neighbor = (
                        row["target_entity_id"]
                        if row["source_entity_id"] == current
                        else row["source_entity_id"]
                    )
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_frontier.add(neighbor)
            frontier = next_frontier
            if not frontier:
                break
        return result

    @staticmethod
    def _feedback_payload(row: RelevanceFeedbackRow) -> dict[str, Any]:
        return {
            "feedback_id": row.feedback_id,
            "collection_id": row.collection_id,
            "resource_id": row.resource_id,
            "document_id": row.document_id,
            "chunk_id": row.chunk_id,
            "query_hash": row.query_hash,
            "label": row.label,
            "rank": row.rank,
            "actor": row.actor,
            "context": dict(row.context_json or {}),
            "created_at": row.created_at,
        }

    def record_relevance_feedback(
        self,
        *,
        collection_id: str,
        resource_id: str,
        document_id: str,
        chunk_id: str,
        query: str,
        label: str,
        rank: int | None = None,
        actor: str | None = None,
        context: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        allowed = {"relevant", "partially_relevant", "not_relevant"}
        if label not in allowed:
            raise ValueError("invalid relevance feedback label")
        query_hash = hashlib.sha256(query.strip().encode("utf-8")).hexdigest()

        with self._require_factory()() as session:
            chunk = session.get(ChunkRow, chunk_id)
            document = session.get(DocumentRow, document_id)
            resource = session.get(ResourceRow, resource_id)
            if chunk is None or document is None or resource is None:
                raise ValueError("feedback target does not exist")
            if chunk.document_id != document_id:
                raise ValueError("feedback chunk/document mismatch")
            if document.resource_id != resource_id:
                raise ValueError("feedback document/resource mismatch")
            if resource.collection_id != collection_id:
                raise ValueError("feedback target is outside the collection")

            row = RelevanceFeedbackRow(
                collection_id=collection_id,
                resource_id=resource_id,
                document_id=document_id,
                chunk_id=chunk_id,
                query_hash=query_hash,
                label=label,
                rank=rank,
                actor=actor,
                context_json=dict(context or {}),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._feedback_payload(row)

    def list_relevance_feedback(
        self,
        *,
        collection_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._require_factory()() as session:
            if session.get(CollectionRow, collection_id) is None:
                raise CollectionNotFound(collection_id)
            rows = session.scalars(
                select(RelevanceFeedbackRow)
                .where(RelevanceFeedbackRow.collection_id == collection_id)
                .order_by(
                    RelevanceFeedbackRow.created_at.desc(),
                    RelevanceFeedbackRow.feedback_id.desc(),
                )
                .limit(max(1, min(limit, 1000)))
            ).all()
            return [self._feedback_payload(row) for row in rows]

    def relevance_feedback_summary(self, collection_id: str) -> dict[str, Any]:
        with self._require_factory()() as session:
            if session.get(CollectionRow, collection_id) is None:
                raise CollectionNotFound(collection_id)
            counts = dict(
                session.execute(
                    select(
                        RelevanceFeedbackRow.label,
                        func.count(RelevanceFeedbackRow.feedback_id),
                    )
                    .where(RelevanceFeedbackRow.collection_id == collection_id)
                    .group_by(RelevanceFeedbackRow.label)
                ).all()
            )
            return {
                "collection_id": collection_id,
                "total": int(sum(counts.values())),
                "relevant": int(counts.get("relevant", 0)),
                "partially_relevant": int(counts.get("partially_relevant", 0)),
                "not_relevant": int(counts.get("not_relevant", 0)),
            }
