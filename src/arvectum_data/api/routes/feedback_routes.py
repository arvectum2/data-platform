from __future__ import annotations


from fastapi import (
    APIRouter,
    Depends,
)

from ..schemas import (
    RelevanceFeedbackRequest,
    RelevanceFeedbackResponse,
    RelevanceFeedbackSummaryResponse,
)

from .context import RouteContext



def register_feedback_routes(router: APIRouter, context: RouteContext) -> None:
    runtime = context.runtime
    map_service_error = context.map_service_error

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
