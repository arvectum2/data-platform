from __future__ import annotations


from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
)

from ...modes import mode_profile
from ...search import SearchQuery
from ..schemas import (
    ConnectorCredentialCreateRequest,
    ConnectorCredentialResponse,
    ConnectorCredentialRotateRequest,
    ConnectorHealthResponse,
    DiscoveryRequest,
    DiscoveryResponse,
    SearchHitResponse,
    SearchExecutionDiagnosticsResponse,
    SearchRequest,
    SearchResponse,
)

from .context import RouteContext


def register_search_connector_routes(router: APIRouter, context: RouteContext) -> None:
    resolved = context.settings
    runtime = context.runtime
    require_consumer_identity = context.require_consumer_identity
    map_service_error = context.map_service_error

    @router.post(
        "/search",
        response_model=SearchResponse,
        tags=["search"],
    )
    def search_endpoint(
        payload: SearchRequest,
        x_arvectum_consumer: str | None = Header(default=None),
        x_arvectum_consumer_key: str | None = Header(default=None),
        runtime_service=Depends(runtime),
    ):
        if len(payload.collections) > resolved.max_search_collections:
            raise HTTPException(
                status_code=413,
                detail="too many collections in one search request",
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
        try:
            search_query = SearchQuery(
                query=payload.query,
                collections=tuple(payload.collections),
                filters={key: tuple(values) for key, values in payload.filters.items()},
                limit=payload.limit,
                mode=payload.mode,
                lexical_weight=payload.lexical_weight,
                vector_weight=payload.vector_weight,
                query_variants=tuple(payload.query_variants),
                query_variant_weight=payload.query_variant_weight,
                expand_query=payload.expand_query,
                query_expansion_limit=payload.query_expansion_limit,
                collapse_by_canonical_uri=payload.collapse_by_canonical_uri,
                rerank=payload.rerank,
                rerank_candidates=payload.rerank_candidates,
                rerank_strategy=payload.rerank_strategy,
                execution_mode=payload.execution_mode,
            )
            stage_diagnostics = ()
            if hasattr(runtime_service, "search_with_execution_diagnostics"):
                (
                    hits,
                    query_expansions,
                    stage_diagnostics,
                ) = runtime_service.search_with_execution_diagnostics(
                    search_query,
                    consumer=consumer,
                )
            elif hasattr(runtime_service, "search_with_diagnostics"):
                hits, query_expansions = runtime_service.search_with_diagnostics(
                    search_query,
                    consumer=consumer,
                )
            else:
                hits = runtime_service.search(search_query, consumer=consumer)
                query_expansions = ()
        except Exception as exc:
            raise map_service_error(exc) from exc

        total_search_ms = next(
            (item.duration_ms for item in stage_diagnostics if item.stage == "total-search"),
            None,
        )
        active_profile = (
            mode_profile(payload.execution_mode) if payload.execution_mode is not None else None
        )

        return SearchResponse(
            query=payload.query,
            execution_mode=payload.execution_mode,
            hits=[
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
            query_expansions=[
                {
                    "text": item.text,
                    "source": item.source,
                    "weight": item.weight,
                }
                for item in query_expansions
            ],
            diagnostics=SearchExecutionDiagnosticsResponse(
                execution_mode=payload.execution_mode,
                total_ms=total_search_ms,
                latency_budget_ms=(
                    active_profile.latency_budget_ms if active_profile is not None else None
                ),
                within_latency_budget=(
                    total_search_ms <= active_profile.latency_budget_ms
                    if active_profile is not None and total_search_ms is not None
                    else None
                ),
                max_model_calls=(
                    active_profile.max_model_calls if active_profile is not None else None
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
                    for item in stage_diagnostics
                ],
            ),
        )

    @router.post(
        "/connectors/credentials",
        response_model=ConnectorCredentialResponse,
        tags=["connectors"],
    )
    def create_connector_credential_endpoint(
        payload: ConnectorCredentialCreateRequest,
        x_arvectum_consumer: str | None = Header(default=None),
        x_arvectum_consumer_key: str | None = Header(default=None),
        runtime_service=Depends(runtime),
    ):
        consumer = require_consumer_identity(
            x_arvectum_consumer,
            x_arvectum_consumer_key,
        )
        try:
            return runtime_service.create_connector_credential(
                consumer_id=consumer,
                connector_name=payload.connector,
                secrets=payload.secrets,
                label=payload.label,
                metadata=payload.metadata,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.get(
        "/connectors/credentials",
        response_model=list[ConnectorCredentialResponse],
        tags=["connectors"],
    )
    def list_connector_credentials_endpoint(
        connector: str | None = None,
        x_arvectum_consumer: str | None = Header(default=None),
        x_arvectum_consumer_key: str | None = Header(default=None),
        runtime_service=Depends(runtime),
    ):
        consumer = require_consumer_identity(
            x_arvectum_consumer,
            x_arvectum_consumer_key,
        )
        try:
            return runtime_service.list_connector_credentials(
                consumer_id=consumer,
                connector_name=connector,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/connectors/credentials/{credential_id}/rotate",
        response_model=ConnectorCredentialResponse,
        tags=["connectors"],
    )
    def rotate_connector_credential_endpoint(
        credential_id: str,
        payload: ConnectorCredentialRotateRequest,
        x_arvectum_consumer: str | None = Header(default=None),
        x_arvectum_consumer_key: str | None = Header(default=None),
        runtime_service=Depends(runtime),
    ):
        consumer = require_consumer_identity(
            x_arvectum_consumer,
            x_arvectum_consumer_key,
        )
        try:
            return runtime_service.rotate_connector_credential(
                credential_id,
                consumer_id=consumer,
                secrets=payload.secrets,
                label=payload.label,
                metadata=payload.metadata,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/connectors/credentials/{credential_id}/revoke",
        response_model=ConnectorCredentialResponse,
        tags=["connectors"],
    )
    def revoke_connector_credential_endpoint(
        credential_id: str,
        x_arvectum_consumer: str | None = Header(default=None),
        x_arvectum_consumer_key: str | None = Header(default=None),
        runtime_service=Depends(runtime),
    ):
        consumer = require_consumer_identity(
            x_arvectum_consumer,
            x_arvectum_consumer_key,
        )
        try:
            return runtime_service.revoke_connector_credential(
                credential_id,
                consumer_id=consumer,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.get(
        "/connectors",
        response_model=list[ConnectorHealthResponse],
        tags=["connectors"],
    )
    def connector_status_endpoint(runtime_service=Depends(runtime)):
        try:
            return runtime_service.connector_status()
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/discover",
        response_model=DiscoveryResponse,
        tags=["connectors"],
    )
    def discover_endpoint(
        payload: DiscoveryRequest,
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
            discover_kwargs = {
                "connector_name": payload.connector,
                "query": payload.query,
                "cursor": payload.cursor,
                "limit": payload.limit,
            }
            if consumer is not None:
                discover_kwargs["consumer"] = consumer
            if payload.credential_id is not None:
                discover_kwargs["credential_id"] = payload.credential_id
            page = runtime_service.discover(**discover_kwargs)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="connector not found") from exc
        except Exception as exc:
            raise map_service_error(exc) from exc

        return DiscoveryResponse(
            resources=[
                {
                    "canonical_uri": item.canonical_uri,
                    "provider": item.provider,
                    "source_type": item.source_type,
                    "external_id": item.external_id,
                    "title": item.title,
                    "snippet": item.snippet,
                    "rank": item.rank,
                    "metadata": dict(item.metadata),
                }
                for item in page.resources
            ],
            next_cursor=page.next_cursor,
            warnings=list(page.warnings),
        )
