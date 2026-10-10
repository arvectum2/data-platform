from __future__ import annotations


from fastapi import (
    APIRouter,
    Depends,
    Header,
)

from ...modes import mode_profile
from ..schemas import (
    ResearchRequest,
    ResearchExecutionDiagnosticsResponse,
    ResearchResponse,
    SearchHitResponse,
)

from .context import RouteContext




def register_research_routes(router: APIRouter, context: RouteContext) -> None:
    runtime = context.runtime
    require_consumer_identity = context.require_consumer_identity
    map_service_error = context.map_service_error

    @router.post(
        "/research",
        response_model=ResearchResponse,
        tags=["research"],
    )
    def research_endpoint(
        payload: ResearchRequest,
        x_arvectum_consumer: str | None = Header(default=None),
        x_arvectum_consumer_key: str | None = Header(default=None),
        runtime_service=Depends(runtime),
    ):
        consumer = None
        if (
            payload.credential_id is not None
            or x_arvectum_consumer is not None
            or x_arvectum_consumer_key is not None
        ):
            consumer = require_consumer_identity(
                x_arvectum_consumer,
                x_arvectum_consumer_key,
            )
        try:
            research_kwargs = {
                "query": payload.query,
                "collection_id": payload.collection_id,
                "connector": payload.connector,
                "source_limit": payload.source_limit,
                "evidence_limit": payload.evidence_limit,
                "consumer": consumer,
                "rerank": payload.rerank,
                "expand_query": payload.expand_query,
            }
            if payload.credential_id is not None:
                research_kwargs["credential_id"] = payload.credential_id
            result = runtime_service.research(**research_kwargs)
        except Exception as exc:
            raise map_service_error(exc) from exc
        research_total_ms = next(
            (item.duration_ms for item in result.diagnostics if item.stage == "total-research"),
            None,
        )
        research_profile = (
            mode_profile(payload.execution_mode) if payload.execution_mode is not None else None
        )

        return ResearchResponse(
            query=result.query,
            execution_mode=payload.execution_mode,
            answer=result.answer.answer,
            claims=[
                {"text": claim.text, "chunk_ids": list(claim.chunk_ids)}
                for claim in result.answer.claims
            ],
            contradictions=list(result.answer.contradictions),
            uncertainty=result.answer.uncertainty,
            abstained=result.answer.abstained,
            sources=[
                {
                    "canonical_uri": source.canonical_uri,
                    "title": source.title,
                    "provider": source.provider,
                    "rank": source.rank,
                    "ingested": source.ingested,
                    "error": source.error,
                }
                for source in result.sources
            ],
            evidence=[
                SearchHitResponse(
                    chunk_id=hit.chunk_id,
                    document_id=hit.document_id,
                    resource_id=hit.resource_id,
                    canonical_uri=hit.canonical_uri,
                    title=hit.title,
                    preview=hit.preview,
                    text=hit.text,
                    scores={
                        "lexical": hit.scores.lexical,
                        "vector": hit.scores.vector,
                        "fusion": hit.scores.fusion,
                        "rerank": hit.scores.rerank,
                    },
                    evidence=[
                        {
                            "resource_id": evidence.resource_id,
                            "document_id": evidence.document_id,
                            "chunk_id": evidence.chunk_id,
                            "canonical_uri": evidence.canonical_uri,
                        }
                        for evidence in hit.evidence
                    ],
                    metadata=dict(hit.metadata),
                )
                for hit in result.evidence
            ],
            warnings=list(result.warnings),
            diagnostics=ResearchExecutionDiagnosticsResponse(
                execution_mode=payload.execution_mode,
                total_ms=research_total_ms,
                latency_budget_ms=(
                    research_profile.latency_budget_ms if research_profile is not None else None
                ),
                within_latency_budget=(
                    research_total_ms <= research_profile.latency_budget_ms
                    if research_profile is not None and research_total_ms is not None
                    else None
                ),
                max_model_calls=(
                    research_profile.max_model_calls if research_profile is not None else None
                ),
                stages=[
                    {
                        "stage": item.stage,
                        "status": item.status,
                        "duration_ms": item.duration_ms,
                        "provider": item.provider,
                        "model": item.model,
                        "metadata": dict(item.metadata),
                    }
                    for item in result.diagnostics
                ],
            ),
        )
