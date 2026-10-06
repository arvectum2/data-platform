from __future__ import annotations

import hmac
import time
import uuid
from collections import deque
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
)
import uvicorn

from ..acquisition.security import UnsafeURL
from ..observability import configure_logging
from .config import Settings
from .routes import (
    RouteContext,
    register_billing_usage_routes,
    register_collections_ingest_routes,
    register_index_graph_feedback_routes,
    register_research_memory_sync_extract_routes,
    register_search_connector_routes,
    register_system_auth_routes,
)
from .service import (
    CollectionAccessDenied,
    InvoicePricingIncomplete,
    InvoiceNotFound,
    BillingCatalogNotFound,
    BillingAssignmentNotFound,
    CollectionNotFound,
    ConnectorCredentialNotFound,
    ConsumerKeyNotFound,
    DataPlatformService,
    EmbeddingContractMismatch,
    EntityNotFound,
    IndexJobNotFound,
    MemoryNotFound,
    PlatformNotConfigured,
    TenantQuotaExceeded,
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
    service.state.usage_metering_errors = 0
    operation_names = (
        "process",
        "ingest",
        "search",
        "answer",
        "research",
        "discover",
        "extract",
        "reindex",
    )
    service.state.operation_metrics = {
        name: {"requests": 0, "errors": 0, "total_ms": 0, "max_ms": 0} for name in operation_names
    }
    service.state.operation_latency_samples = {name: deque(maxlen=256) for name in operation_names}

    def operation_name(method: str, path: str) -> str | None:
        if method == "POST" and path == "/v1/process/document":
            return "process"
        if method == "POST" and path in {"/v1/ingest/document", "/v1/ingest/url"}:
            return "ingest"
        if method == "POST" and path == "/v1/search":
            return "search"
        if method == "POST" and path == "/v1/answer":
            return "answer"
        if method == "POST" and path == "/v1/research":
            return "research"
        if method == "POST" and path == "/v1/discover":
            return "discover"
        if method == "POST" and path == "/v1/extract":
            return "extract"
        if method == "POST" and path == "/v1/index/rebuild":
            return "reindex"
        return None

    def usage_operation_name(method: str, path: str) -> str | None:
        if method == "POST" and path == "/v1/search":
            return "search"
        if method == "POST" and path == "/v1/answer":
            return "answer"
        if method == "POST" and path == "/v1/research":
            return "research"
        if method == "POST" and path == "/v1/memory":
            return "memory_write"
        if method == "DELETE" and path.startswith("/v1/memory/"):
            return "memory_delete"
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
            duration_ms = max(0, int(round((time.perf_counter() - started) * 1000)))
            if operation is not None:
                metric = service.state.operation_metrics[operation]
                metric["requests"] += 1
                if status_code >= 400:
                    metric["errors"] += 1
                metric["total_ms"] += duration_ms
                metric["max_ms"] = max(metric["max_ms"], duration_ms)
                service.state.operation_latency_samples[operation].append(duration_ms)

            usage_operation = usage_operation_name(request.method, request.url.path)
            consumer_id = request.headers.get("X-Arvectum-Consumer", "").strip()
            consumer_key = request.headers.get("X-Arvectum-Consumer-Key", "").strip()
            if (
                usage_operation is not None
                and consumer_id
                and consumer_key
                and status_code not in {401, 403}
            ):
                platform = service.state.platform_service
                if hasattr(platform, "record_usage_event"):
                    raw_length = request.headers.get("content-length", "").strip()
                    request_bytes = None
                    if raw_length:
                        try:
                            request_bytes = max(0, int(raw_length))
                        except ValueError:
                            request_bytes = None
                    try:
                        platform.record_usage_event(
                            consumer_id=consumer_id,
                            operation=usage_operation,
                            request_id=request_id,
                            status_code=status_code,
                            duration_ms=duration_ms,
                            request_bytes=request_bytes,
                        )
                    except Exception:
                        service.state.usage_metering_errors += 1

    @service.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": resolved.service_name,
            "environment": resolved.environment,
            "version": _package_version(),
        }

    def require_internal_key(
        request: Request,
        x_arvectum_key: str | None = Header(default=None),
        x_arvectum_consumer: str | None = Header(default=None),
        x_arvectum_consumer_key: str | None = Header(default=None),
    ) -> None:
        expected = resolved.internal_api_key
        if not expected:
            return
        if x_arvectum_key is not None and hmac.compare_digest(
            x_arvectum_key,
            expected,
        ):
            return
        external_data_plane = (
            request.url.path
            in {
                "/v1/search",
                "/v1/answer",
                "/v1/research",
                "/v1/memory",
                "/v1/discover",
            }
            or request.url.path.startswith("/v1/memory/")
            or request.url.path.startswith("/v1/connectors/credentials")
        )
        if external_data_plane and (
            x_arvectum_consumer is not None or x_arvectum_consumer_key is not None
        ):
            require_consumer_identity(
                x_arvectum_consumer,
                x_arvectum_consumer_key,
            )
            return
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
        static_valid = expected is not None and hmac.compare_digest(consumer_key, expected)
        managed_valid = False
        if not static_valid:
            platform = runtime()
            if hasattr(platform, "authenticate_consumer_key"):
                managed_valid = platform.authenticate_consumer_key(
                    consumer,
                    consumer_key,
                )
        if not static_valid and not managed_valid:
            raise HTTPException(status_code=403, detail="invalid consumer credentials")
        return consumer

    def runtime():
        return service.state.platform_service

    def map_service_error(exc: Exception) -> HTTPException:
        if isinstance(exc, PlatformNotConfigured):
            return HTTPException(status_code=503, detail=str(exc))
        if isinstance(exc, CollectionNotFound):
            return HTTPException(status_code=404, detail="collection not found")
        if isinstance(exc, ConsumerKeyNotFound):
            return HTTPException(status_code=404, detail="consumer key not found")
        if isinstance(exc, ConnectorCredentialNotFound):
            return HTTPException(status_code=404, detail="connector credential not found")
        if isinstance(exc, BillingCatalogNotFound):
            return HTTPException(status_code=404, detail="billing catalog not found")
        if isinstance(exc, BillingAssignmentNotFound):
            return HTTPException(status_code=404, detail=str(exc))
        if isinstance(exc, InvoiceNotFound):
            return HTTPException(status_code=404, detail="invoice not found")
        if isinstance(exc, InvoicePricingIncomplete):
            return HTTPException(status_code=409, detail=str(exc))
        if isinstance(exc, CollectionAccessDenied):
            return HTTPException(status_code=403, detail="collection access denied")
        if isinstance(exc, TenantQuotaExceeded):
            return HTTPException(status_code=429, detail=str(exc))
        if isinstance(exc, IndexJobNotFound):
            return HTTPException(status_code=404, detail="index job not found")
        if isinstance(exc, MemoryNotFound):
            return HTTPException(status_code=404, detail="memory not found")
        if isinstance(exc, EntityNotFound):
            return HTTPException(status_code=404, detail="entity not found")
        if isinstance(exc, (EmbeddingContractMismatch, UnsafeURL, ValueError)):
            return HTTPException(status_code=400, detail=str(exc))
        return HTTPException(status_code=500, detail="internal data platform error")

    router = APIRouter(
        prefix="/v1",
        dependencies=[Depends(require_internal_key)],
    )

    route_context = RouteContext(
        settings=resolved,
        app=service,
        runtime=runtime,
        require_consumer_identity=require_consumer_identity,
        map_service_error=map_service_error,
    )
    register_system_auth_routes(router, route_context)
    register_billing_usage_routes(router, route_context)
    register_collections_ingest_routes(router, route_context)
    register_search_connector_routes(router, route_context)
    register_index_graph_feedback_routes(router, route_context)
    register_research_memory_sync_extract_routes(router, route_context)

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
