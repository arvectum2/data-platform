from __future__ import annotations


from fastapi import (
    APIRouter,
    Depends,
    Header,
)

from ..schemas import (
    EntityGraphEdgeResponse,
    EntityRelationResponse,
    EntityRelationReviewRequest,
    GraphSuggestionRequest,
    GraphSuggestionResponse,
)

from .context import RouteContext




def register_graph_relation_routes(router: APIRouter, context: RouteContext) -> None:
    runtime = context.runtime
    require_consumer_identity = context.require_consumer_identity
    map_service_error = context.map_service_error

    @router.get(
        "/entities/{entity_id}/relations",
        response_model=list[EntityRelationResponse],
        tags=["entities"],
    )
    def list_entity_relations_endpoint(
        entity_id: str,
        direction: str = "both",
        relation_type: str | None = None,
        status: str | None = "canonical",
        limit: int = 100,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.list_entity_relations(
                entity_id,
                direction=direction,
                relation_type=relation_type,
                status=status,
                limit=limit,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/graph/suggestions",
        response_model=GraphSuggestionResponse,
        tags=["entities"],
    )
    def graph_suggestions_endpoint(
        payload: GraphSuggestionRequest,
        x_arvectum_consumer: str | None = Header(default=None),
        x_arvectum_consumer_key: str | None = Header(default=None),
        runtime_service=Depends(runtime),
    ):
        consumer = None
        if x_arvectum_consumer is not None or x_arvectum_consumer_key is not None:
            consumer = require_consumer_identity(
                x_arvectum_consumer,
                x_arvectum_consumer_key,
            )
        try:
            result = runtime_service.suggest_graph_enrichment(
                query=payload.query,
                collection_id=payload.collection_id,
                entity_ids=payload.entity_ids,
                evidence_limit=payload.evidence_limit,
                consumer=consumer,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc
        return GraphSuggestionResponse(
            aliases=[
                {"entity_id": item.entity_id, "alias": item.alias, "chunk_id": item.chunk_id}
                for item in result.aliases
            ],
            relations=[
                {
                    "source_entity_id": item.source_entity_id,
                    "target_entity_id": item.target_entity_id,
                    "relation_type": item.relation_type,
                    "chunk_id": item.chunk_id,
                    "valid_from": item.valid_from,
                    "valid_to": item.valid_to,
                }
                for item in result.relations
            ],
        )

    @router.post(
        "/entity-relations/{relation_id}/review",
        response_model=EntityRelationResponse,
        tags=["entities"],
    )
    def review_entity_relation_endpoint(
        relation_id: str,
        payload: EntityRelationReviewRequest,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.review_entity_relation(
                relation_id,
                decision=payload.decision,
                reviewer=payload.reviewer,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.get(
        "/entities/{entity_id}/graph",
        response_model=list[EntityGraphEdgeResponse],
        tags=["entities"],
    )
    def traverse_entity_graph_endpoint(
        entity_id: str,
        max_depth: int = 2,
        relation_type: str | None = None,
        limit: int = 200,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.traverse_entity_graph(
                entity_id,
                max_depth=max_depth,
                relation_type=relation_type,
                limit=limit,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc
