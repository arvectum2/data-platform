from __future__ import annotations

import hmac
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
from .schemas import (
    CollectionCreateRequest,
    CollectionResponse,
    ExtractDecisionResponse,
    ExtractRequest,
    ExtractResponse,
    IndexJobResponse,
    IndexRebuildRequest,
    IngestResponse,
    SearchHitResponse,
    SearchRequest,
    SearchResponse,
    StatusResponse,
    UrlIngestRequest,
)
from .service import (
    CollectionNotFound,
    DataPlatformService,
    EmbeddingContractMismatch,
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

    @service.middleware("http")
    async def request_context(request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        service.state.request_count += 1
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

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

    def runtime():
        return service.state.platform_service

    def map_service_error(exc: Exception) -> HTTPException:
        if isinstance(exc, PlatformNotConfigured):
            return HTTPException(status_code=503, detail=str(exc))
        if isinstance(exc, CollectionNotFound):
            return HTTPException(status_code=404, detail="collection not found")
        if isinstance(exc, IndexJobNotFound):
            return HTTPException(status_code=404, detail="index job not found")
        if isinstance(exc, (EmbeddingContractMismatch, UnsafeURL, ValueError)):
            return HTTPException(status_code=400, detail=str(exc))
        return HTTPException(status_code=500, detail="internal data platform error")

    router = APIRouter(
        prefix="/v1",
        dependencies=[Depends(require_internal_key)],
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
        return payload

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
        "/ingest/document",
        response_model=IngestResponse,
        tags=["ingest"],
    )
    async def ingest_document_endpoint(
        collection_id: str = Form(...),
        file: UploadFile = File(...),
        title: str | None = Form(default=None),
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
        runtime_service=Depends(runtime),
    ):
        try:
            hits = runtime_service.search(
                SearchQuery(
                    query=payload.query,
                    collections=tuple(payload.collections),
                    filters={
                        key: tuple(values)
                        for key, values in payload.filters.items()
                    },
                    limit=payload.limit,
                    mode=payload.mode,
                )
            )
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
                min_confidence=field.min_confidence,
                min_margin=field.min_margin,
                aliases=tuple(field.aliases),
            )
            for field in payload.fields
        ]
        warnings: list[str] = []
        try:
            if payload.url:
                pipeline_result = runtime_service.extract_url(
                    url=payload.url,
                    fields=fields,
                )
                result = pipeline_result.extraction
                warnings = list(pipeline_result.acquisition.warnings)
            else:
                result = runtime_service.extract(
                    asset_id=payload.asset_id,
                    source_url=payload.source_url,
                    text=payload.text,
                    html=payload.html,
                    attributes=payload.attributes,
                    fields=fields,
                )
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
