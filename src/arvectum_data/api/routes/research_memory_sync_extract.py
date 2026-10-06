from __future__ import annotations


from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
)

from ...engine import FieldSpec
from ...modes import mode_profile
from ...search import SearchQuery
from ..schemas import (
    AnswerRequest,
    AnswerResponse,
    ExtractDecisionResponse,
    ExtractRequest,
    ExtractResponse,
    MemoryWriteRequest,
    MemoryWriteResponse,
    RefreshPolicyRequest,
    RefreshPolicyResponse,
    RefreshResultResponse,
    RefreshRunResponse,
    ResearchRequest,
    ResearchExecutionDiagnosticsResponse,
    ResearchResponse,
    SearchHitResponse,
)

from .context import RouteContext


def register_research_memory_sync_extract_routes(router: APIRouter, context: RouteContext) -> None:
    resolved = context.settings
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

    @router.post("/memory", response_model=MemoryWriteResponse, tags=["memory"])
    def write_memory_endpoint(
        payload: MemoryWriteRequest,
        x_arvectum_consumer: str | None = Header(default=None),
        x_arvectum_consumer_key: str | None = Header(default=None),
        runtime_service=Depends(runtime),
    ):
        consumer = require_consumer_identity(x_arvectum_consumer, x_arvectum_consumer_key)
        try:
            return runtime_service.write_memory(
                collection_id=payload.collection_id,
                text=payload.text,
                kind=payload.kind,
                producer=consumer,
                consumer=consumer,
                title=payload.title,
                source_chunk_ids=payload.source_chunk_ids,
                model_provider=payload.model_provider,
                model_name=payload.model_name,
                model_version=payload.model_version,
                subject_key=payload.subject_key,
                conflict_policy=payload.conflict_policy,
                metadata=payload.metadata,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.delete("/memory/{record_id}", status_code=204, tags=["memory"])
    def delete_memory_endpoint(
        record_id: str,
        x_arvectum_consumer: str | None = Header(default=None),
        x_arvectum_consumer_key: str | None = Header(default=None),
        runtime_service=Depends(runtime),
    ):
        consumer = require_consumer_identity(x_arvectum_consumer, x_arvectum_consumer_key)
        try:
            runtime_service.delete_memory(record_id, consumer=consumer)
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.put(
        "/resources/{resource_id}/refresh-policy",
        response_model=RefreshPolicyResponse,
        tags=["sync"],
    )
    def configure_refresh_policy_endpoint(
        resource_id: str,
        payload: RefreshPolicyRequest,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.configure_resource_refresh(
                resource_id,
                interval_seconds=payload.interval_seconds,
                missing_after_failures=payload.missing_after_failures,
                enabled=payload.enabled,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/resources/{resource_id}/refresh",
        response_model=RefreshResultResponse,
        tags=["sync"],
    )
    def refresh_resource_endpoint(resource_id: str, runtime_service=Depends(runtime)):
        try:
            result = runtime_service.refresh_resource(resource_id)
            return RefreshResultResponse(
                refresh_run_id=result.refresh_run_id,
                resource_id=result.resource_id,
                outcome=result.outcome,
                changed=result.changed,
                previous_hash=result.previous_hash,
                current_hash=result.current_hash,
                next_refresh_at=result.next_refresh_at,
                detail=dict(result.detail),
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/sync/refresh-due",
        response_model=list[RefreshResultResponse],
        tags=["sync"],
    )
    def refresh_due_endpoint(limit: int = 50, runtime_service=Depends(runtime)):
        try:
            results = runtime_service.refresh_due_resources(limit=limit)
            return [
                RefreshResultResponse(
                    refresh_run_id=item.refresh_run_id,
                    resource_id=item.resource_id,
                    outcome=item.outcome,
                    changed=item.changed,
                    previous_hash=item.previous_hash,
                    current_hash=item.current_hash,
                    next_refresh_at=item.next_refresh_at,
                    detail=dict(item.detail),
                )
                for item in results
            ]
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.get(
        "/resources/{resource_id}/refresh-runs",
        response_model=list[RefreshRunResponse],
        tags=["sync"],
    )
    def refresh_runs_endpoint(resource_id: str, limit: int = 50, runtime_service=Depends(runtime)):
        try:
            return runtime_service.list_refresh_runs(resource_id, limit=limit)
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/extract",
        response_model=ExtractResponse,
        tags=["extraction"],
    )
    def extract_endpoint(
        payload: ExtractRequest,
        runtime_service=Depends(runtime),
    ):
        fields = [
            FieldSpec(
                key=field.key,
                required=field.required,
                value_type=field.value_type,
                min_confidence=field.min_confidence,
                min_margin=field.min_margin,
                aliases=tuple(field.aliases),
            )
            for field in payload.fields
        ]
        warnings: list[str] = []
        try:
            if payload.url:
                url_kwargs = {"url": payload.url, "fields": fields}
                if payload.use_model:
                    url_kwargs["use_model"] = True
                pipeline_result = runtime_service.extract_url(**url_kwargs)
                result = pipeline_result.extraction
                warnings = list(pipeline_result.acquisition.warnings)
            else:
                extract_kwargs = {
                    "asset_id": payload.asset_id,
                    "source_url": payload.source_url,
                    "text": payload.text,
                    "html": payload.html,
                    "attributes": payload.attributes,
                    "fields": fields,
                }
                if payload.use_model:
                    extract_kwargs["use_model"] = True
                result = runtime_service.extract(**extract_kwargs)
        except Exception as exc:
            raise map_service_error(exc) from exc

        decisions = {
            key: ExtractDecisionResponse(
                status=decision.status.value,
                selected_value=(decision.selected.value if decision.selected is not None else None),
                selected_candidate_id=(
                    decision.selected.candidate_id if decision.selected is not None else None
                ),
                confidence=(
                    decision.selected.confidence if decision.selected is not None else None
                ),
                provider=(decision.selected.provider if decision.selected is not None else None),
                evidence=(
                    [
                        {
                            "kind": evidence.kind,
                            "source_ref": evidence.source_ref,
                            "excerpt": evidence.excerpt,
                            "metadata": dict(evidence.metadata),
                        }
                        for evidence in decision.selected.evidence
                    ]
                    if decision.selected is not None
                    else []
                ),
                candidates=[
                    {
                        "candidate_id": candidate.candidate_id,
                        "value": candidate.value,
                        "confidence": candidate.confidence,
                        "provider": candidate.provider,
                        "evidence": [
                            {
                                "kind": evidence.kind,
                                "source_ref": evidence.source_ref,
                                "excerpt": evidence.excerpt,
                                "metadata": dict(evidence.metadata),
                            }
                            for evidence in candidate.evidence
                        ],
                    }
                    for candidate in decision.candidates
                ],
                reason=decision.reason,
            )
            for key, decision in result.decisions.items()
        }
        return ExtractResponse(
            values=result.values(include_unconfirmed=True),
            requires_confirmation=result.requires_confirmation,
            unresolved_required_fields=list(result.unresolved_required_fields),
            decisions=decisions,
            provider_errors=dict(result.provider_errors),
            warnings=warnings,
        )
