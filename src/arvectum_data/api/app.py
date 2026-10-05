from __future__ import annotations

import hmac
import time
import uuid
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
)
import uvicorn

from ..acquisition.security import UnsafeURL
from ..engine import FieldSpec
from ..observability import configure_logging
from ..search import SearchQuery
from .config import Settings
from .contract import (
    CONSUMER_CONTRACT_CAPABILITIES,
    CONSUMER_CONTRACT_NAME,
    CONSUMER_CONTRACT_VERSION,
)
from .schemas import (
    AnswerRequest,
    AnswerResponse,
    CollectionCreateRequest,
    CollectionResponse,
    CollectionStatsResponse,
    ConnectorHealthResponse,
    ConsumerContractResponse,
    DiscoveryRequest,
    DiscoveryResponse,
    EntityCreateRequest,
    EntityRelationCreateRequest,
    EntityRelationResponse,
    EntityResolveRequest,
    EntityResolveResponse,
    EntityResponse,
    ExtractDecisionResponse,
    ExtractRequest,
    ExtractResponse,
    IndexJobResponse,
    IndexRebuildRequest,
    IngestResponse,
    ProcessDocumentResponse,
    RelevanceFeedbackRequest,
    RelevanceFeedbackResponse,
    RelevanceFeedbackSummaryResponse,
    SearchHitResponse,
    SearchRequest,
    SearchResponse,
    StatusResponse,
    UrlIngestRequest,
)
from .service import (
    CollectionAccessDenied,
    CollectionNotFound,
    DataPlatformService,
    EmbeddingContractMismatch,
    EntityNotFound,
    IndexJobNotFound,
    PlatformNotConfigured,
)


def _package_version() -> str:
    try:
        return version("arvectum-data")
    except PackageNotFoundError:
        return "0.0.0+local"


def create_app(
    settings: Settings | None = None,
    *,
    platform_service: Any | None = None,
) -> FastAPI:
    resolved = settings or Settings()
    configure_logging(resolved.log_level)

    service = FastAPI(
        title="Arvectum Data Platform",
        version=_package_version(),
    )
    service.state.platform_service = (
        platform_service if platform_service is not None else DataPlatformService(resolved)
    )
    service.state.request_count = 0
    service.state.operation_metrics = {
        name: {"requests": 0, "errors": 0, "total_ms": 0, "max_ms": 0}
        for name in ("process", "ingest", "search", "answer", "discover", "extract", "reindex")
    }

    def operation_name(method: str, path: str) -> str | None:
        if method == "POST" and path == "/v1/process/document":
            return "process"
        if method == "POST" and path in {"/v1/ingest/document", "/v1/ingest/url"}:
            return "ingest"
        if method == "POST" and path == "/v1/search":
            return "search"
        if method == "POST" and path == "/v1/answer":
            return "answer"
        if method == "POST" and path == "/v1/discover":
            return "discover"
        if method == "POST" and path == "/v1/extract":
            return "extract"
        if method == "POST" and path == "/v1/index/rebuild":
            return "reindex"
        return None

    @service.middleware("http")
    async def request_context(request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        service.state.request_count += 1
        operation = operation_name(request.method, request.url.path)
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            if operation is not None:
                duration_ms = max(0, int(round((time.perf_counter() - started) * 1000)))
                metric = service.state.operation_metrics[operation]
                metric["requests"] += 1
                if status_code >= 400:
                    metric["errors"] += 1
                metric["total_ms"] += duration_ms
                metric["max_ms"] = max(metric["max_ms"], duration_ms)

    @service.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": resolved.service_name,
            "environment": resolved.environment,
            "version": _package_version(),
        }

    def require_internal_key(x_arvectum_key: str | None = Header(default=None)) -> None:
        expected = resolved.internal_api_key
        if not expected:
            return
        if x_arvectum_key is None or not hmac.compare_digest(x_arvectum_key, expected):
            raise HTTPException(status_code=401, detail="invalid internal API key")

    def require_consumer_identity(
        consumer: str | None,
        consumer_key: str | None,
    ) -> str:
        if not consumer or not consumer_key:
            raise HTTPException(
                status_code=403,
                detail="consumer identity is required for federated or restricted search",
            )
        expected = resolved.consumer_api_keys.get(consumer)
        if expected is None or not hmac.compare_digest(consumer_key, expected):
            raise HTTPException(status_code=403, detail="invalid consumer credentials")
        return consumer

    def runtime():
        return service.state.platform_service

    def map_service_error(exc: Exception) -> HTTPException:
        if isinstance(exc, PlatformNotConfigured):
            return HTTPException(status_code=503, detail=str(exc))
        if isinstance(exc, CollectionNotFound):
            return HTTPException(status_code=404, detail="collection not found")
        if isinstance(exc, CollectionAccessDenied):
            return HTTPException(status_code=403, detail="collection access denied")
        if isinstance(exc, IndexJobNotFound):
            return HTTPException(status_code=404, detail="index job not found")
        if isinstance(exc, EntityNotFound):
            return HTTPException(status_code=404, detail="entity not found")
        if isinstance(exc, (EmbeddingContractMismatch, UnsafeURL, ValueError)):
            return HTTPException(status_code=400, detail=str(exc))
        return HTTPException(status_code=500, detail="internal data platform error")

    router = APIRouter(
        prefix="/v1",
        dependencies=[Depends(require_internal_key)],
    )

    @router.get(
        "/contract",
        response_model=ConsumerContractResponse,
        tags=["system"],
    )
    def consumer_contract() -> ConsumerContractResponse:
        return ConsumerContractResponse(
            name=CONSUMER_CONTRACT_NAME,
            version=CONSUMER_CONTRACT_VERSION,
            capabilities=list(CONSUMER_CONTRACT_CAPABILITIES),
        )

    @router.get("/status", response_model=StatusResponse, tags=["system"])
    def status(runtime_service=Depends(runtime)):
        if hasattr(runtime_service, "status"):
            payload = dict(runtime_service.status())
        else:
            payload = {
                "status": "ok",
                "database_configured": True,
                "embedding_provider": "test",
                "embedding_model": "test",
                "embedding_dimension": None,
            }
        payload["requests"] = int(service.state.request_count)
        payload["operations"] = {
            name: dict(values)
            for name, values in service.state.operation_metrics.items()
        }
        return payload

    @router.get("/models/status", tags=["system"])
    def model_status(
        probe: bool = False,
        runtime_service=Depends(runtime),
    ) -> dict[str, dict[str, Any]]:
        if not hasattr(runtime_service, "model_status"):
            return {}
        return runtime_service.model_status(probe=probe)

    @router.get(
        "/collections",
        response_model=list[CollectionResponse],
        tags=["collections"],
    )
    def list_collections(runtime_service=Depends(runtime)):
        try:
            return runtime_service.list_collections()
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/collections",
        response_model=CollectionResponse,
        tags=["collections"],
    )
    def create_collection(
        payload: CollectionCreateRequest,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.create_collection(
                collection_id=payload.collection_id,
                owner=payload.owner,
                name=payload.name,
                default_language=payload.default_language,
                access_policy=(
                    None
                    if payload.access_policy is None
                    else payload.access_policy.model_dump()
                ),
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.get(
        "/collections/{collection_id}",
        response_model=CollectionResponse,
        tags=["collections"],
    )
    def get_collection(
        collection_id: str,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.get_collection(collection_id)
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.get(
        "/collections/{collection_id}/stats",
        response_model=CollectionStatsResponse,
        tags=["collections"],
    )
    def get_collection_stats(
        collection_id: str,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.collection_stats(collection_id)
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/ingest/url",
        response_model=IngestResponse,
        tags=["ingest"],
    )
    def ingest_url_endpoint(
        payload: UrlIngestRequest,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.ingest_url(
                collection_id=payload.collection_id,
                url=payload.url,
                title=payload.title,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/process/document",
        response_model=ProcessDocumentResponse,
        tags=["process"],
    )
    async def process_document_endpoint(
        collection_id: str = Form(...),
        file: UploadFile = File(...),
        title: str | None = Form(default=None),
        canonical_uri: str | None = Form(default=None),
        chunk_size_chars: int = Form(default=1500, ge=1, le=200_000),
        overlap_chars: int = Form(default=200, ge=0, le=100_000),
        min_chunk_chars: int = Form(default=120, ge=1, le=200_000),
        max_chars: int = Form(default=2_000_000, ge=1, le=20_000_000),
        runtime_service=Depends(runtime),
    ):
        content = await file.read(resolved.max_upload_bytes + 1)
        if len(content) > resolved.max_upload_bytes:
            raise HTTPException(status_code=413, detail="uploaded document is too large")
        filename = file.filename or "document.bin"
        if overlap_chars >= chunk_size_chars:
            raise HTTPException(
                status_code=422,
                detail="overlap_chars must be smaller than chunk_size_chars",
            )
        try:
            return runtime_service.process_document_bytes(
                collection_id=collection_id,
                filename=filename,
                content=content,
                title=title,
                canonical_uri=canonical_uri,
                chunk_size_chars=chunk_size_chars,
                overlap_chars=overlap_chars,
                min_chunk_chars=min_chunk_chars,
                max_chars=max_chars,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/ingest/document",
        response_model=IngestResponse,
        tags=["ingest"],
    )
    async def ingest_document_endpoint(
        collection_id: str = Form(...),
        file: UploadFile = File(...),
        title: str | None = Form(default=None),
        canonical_uri: str | None = Form(default=None),
        pre_chunked: bool = Form(default=False),
        runtime_service=Depends(runtime),
    ):
        content = await file.read(resolved.max_upload_bytes + 1)
        if len(content) > resolved.max_upload_bytes:
            raise HTTPException(status_code=413, detail="uploaded document is too large")
        filename = file.filename or "document.bin"
        try:
            return runtime_service.ingest_document_bytes(
                collection_id=collection_id,
                filename=filename,
                content=content,
                title=title,
                canonical_uri=canonical_uri,
                pre_chunked=pre_chunked,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

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
                filters={
                    key: tuple(values)
                    for key, values in payload.filters.items()
                },
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
            )
            if hasattr(runtime_service, "search_with_diagnostics"):
                hits, query_expansions = runtime_service.search_with_diagnostics(
                    search_query,
                    consumer=consumer,
                )
            else:
                hits = runtime_service.search(search_query, consumer=consumer)
                query_expansions = ()
        except Exception as exc:
            raise map_service_error(exc) from exc

        return SearchResponse(
            query=payload.query,
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
        )

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
        runtime_service=Depends(runtime),
    ):
        try:
            page = runtime_service.discover(
                connector_name=payload.connector,
                query=payload.query,
                cursor=payload.cursor,
                limit=payload.limit,
            )
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
        limit: int = 100,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.list_entity_relations(
                entity_id,
                direction=direction,
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
            raise HTTPException(status_code=413, detail="too many collections in one answer request")
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
                {"text": claim.text, "chunk_ids": list(claim.chunk_ids)}
                for claim in answer.claims
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
                selected_value=(
                    decision.selected.value if decision.selected is not None else None
                ),
                selected_candidate_id=(
                    decision.selected.candidate_id
                    if decision.selected is not None
                    else None
                ),
                confidence=(
                    decision.selected.confidence if decision.selected is not None else None
                ),
                provider=(
                    decision.selected.provider if decision.selected is not None else None
                ),
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

    service.include_router(router)
    return service


app = create_app()


def run() -> None:
    settings = Settings()
    uvicorn.run(
        "arvectum_data.api.app:app",
        host=settings.host,
        port=settings.port,
    )
