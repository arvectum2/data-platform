from __future__ import annotations


from fastapi import (
    APIRouter,
    Depends,
    Header,
)

from ..schemas import (
    EntityCreateRequest,
    EntityGraphEdgeResponse,
    EntityRelationCreateRequest,
    EntityRelationResponse,
    EntityRelationReviewRequest,
    EntityResolveRequest,
    EntityResolveResponse,
    EntityResponse,
    GraphSuggestionRequest,
    GraphSuggestionResponse,
    IndexJobResponse,
    IndexRebuildRequest,
    RelevanceFeedbackRequest,
    RelevanceFeedbackResponse,
    RelevanceFeedbackSummaryResponse,
)

from .context import RouteContext


def register_index_graph_feedback_routes(router: APIRouter, context: RouteContext) -> None:
    runtime = context.runtime
    require_consumer_identity = context.require_consumer_identity
    map_service_error = context.map_service_error

    @router.post(
        "/index/rebuild",
        response_model=IndexJobResponse,
        tags=["index"],
    )
    def rebuild_index_endpoint(
        payload: IndexRebuildRequest,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.rebuild_index(payload.collection_id)
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.get(
        "/index/jobs/{run_id}",
        response_model=IndexJobResponse,
        tags=["index"],
    )
    def get_index_job_endpoint(
        run_id: str,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.get_index_job(run_id)
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.get(
        "/index/jobs",
        response_model=list[IndexJobResponse],
        tags=["index"],
    )
    def list_index_jobs_endpoint(
        collection_id: str | None = None,
        limit: int = 50,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.list_index_jobs(
                collection_id=collection_id,
                limit=limit,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/entities",
        response_model=EntityResponse,
        tags=["entities"],
    )
    def create_entity_endpoint(
        payload: EntityCreateRequest,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.create_entity(
                entity_type=payload.entity_type,
                canonical_name=payload.canonical_name,
                aliases=[
                    {
                        "alias_kind": alias.alias_kind,
                        "value": alias.value,
                        "source_collection_id": alias.source_collection_id,
                        "metadata": alias.metadata,
                    }
                    for alias in payload.aliases
                ],
                metadata=payload.metadata,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/entities/resolve",
        response_model=EntityResolveResponse,
        tags=["entities"],
    )
    def resolve_entity_endpoint(
        payload: EntityResolveRequest,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.resolve_entity(
                entity_type=payload.entity_type,
                value=payload.value,
                alias_kind=payload.alias_kind,
                limit=payload.limit,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.get(
        "/entities/{entity_id}",
        response_model=EntityResponse,
        tags=["entities"],
    )
    def get_entity_endpoint(
        entity_id: str,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.get_entity(entity_id)
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/entity-relations",
        response_model=EntityRelationResponse,
        tags=["entities"],
    )
    def create_entity_relation_endpoint(
        payload: EntityRelationCreateRequest,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.create_entity_relation(
                source_entity_id=payload.source_entity_id,
                target_entity_id=payload.target_entity_id,
                relation_type=payload.relation_type,
                status=payload.status,
                valid_from=payload.valid_from,
                valid_to=payload.valid_to,
                source_collection_id=payload.source_collection_id,
                resource_id=payload.resource_id,
                document_id=payload.document_id,
                chunk_id=payload.chunk_id,
                metadata=payload.metadata,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

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

    @router.post(
        "/feedback/relevance",
        response_model=RelevanceFeedbackResponse,
        tags=["feedback"],
    )
    def record_relevance_feedback_endpoint(
        payload: RelevanceFeedbackRequest,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.record_relevance_feedback(
                collection_id=payload.collection_id,
                resource_id=payload.resource_id,
                document_id=payload.document_id,
                chunk_id=payload.chunk_id,
                query=payload.query,
                label=payload.label,
                rank=payload.rank,
                actor=payload.actor,
                context=payload.context,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.get(
        "/feedback/relevance",
        response_model=list[RelevanceFeedbackResponse],
        tags=["feedback"],
    )
    def list_relevance_feedback_endpoint(
        collection_id: str,
        limit: int = 100,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.list_relevance_feedback(
                collection_id=collection_id,
                limit=limit,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.get(
        "/feedback/relevance/summary",
        response_model=RelevanceFeedbackSummaryResponse,
        tags=["feedback"],
    )
    def relevance_feedback_summary_endpoint(
        collection_id: str,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.relevance_feedback_summary(collection_id)
        except Exception as exc:
            raise map_service_error(exc) from exc
