from __future__ import annotations


from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
)

from ...search import SearchQuery
from ..schemas import (
    AnswerRequest,
    AnswerResponse,
    SearchHitResponse,
)

from .context import RouteContext




def register_answer_routes(router: APIRouter, context: RouteContext) -> None:
    resolved = context.settings
    runtime = context.runtime
    require_consumer_identity = context.require_consumer_identity
    map_service_error = context.map_service_error

    @router.post(
        "/answer",
        response_model=AnswerResponse,
        tags=["search"],
    )
    def answer_endpoint(
        payload: AnswerRequest,
        x_arvectum_consumer: str | None = Header(default=None),
        x_arvectum_consumer_key: str | None = Header(default=None),
        runtime_service=Depends(runtime),
    ):
        if len(payload.collections) > resolved.max_search_collections:
            raise HTTPException(
                status_code=413, detail="too many collections in one answer request"
            )
        consumer = None
        if (
            len(payload.collections) > 1
            or x_arvectum_consumer is not None
            or x_arvectum_consumer_key is not None
        ):
            consumer = require_consumer_identity(
                x_arvectum_consumer,
                x_arvectum_consumer_key,
            )
        request = SearchQuery(
            query=payload.query,
            collections=tuple(payload.collections),
            filters={key: tuple(values) for key, values in payload.filters.items()},
            limit=payload.evidence_limit,
            mode=payload.mode,
            rerank=payload.rerank,
            rerank_candidates=max(20, payload.evidence_limit),
            expand_query=payload.expand_query,
        )
        try:
            answer, hits = runtime_service.answer(request, consumer=consumer)
        except Exception as exc:
            raise map_service_error(exc) from exc
        return AnswerResponse(
            query=payload.query,
            answer=answer.answer,
            claims=[
                {"text": claim.text, "chunk_ids": list(claim.chunk_ids)} for claim in answer.claims
            ],
            contradictions=list(answer.contradictions),
            uncertainty=answer.uncertainty,
            abstained=answer.abstained,
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
                for hit in hits
            ],
        )
