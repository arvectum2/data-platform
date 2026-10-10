from __future__ import annotations

from datetime import datetime

from fastapi import (
    APIRouter,
    Depends,
)

from ..schemas import (
    UsageSummaryResponse,
)

from .context import RouteContext



def register_usage_routes(router: APIRouter, context: RouteContext) -> None:
    runtime = context.runtime
    map_service_error = context.map_service_error

    @router.get(
        "/usage/summary",
        response_model=UsageSummaryResponse,
        tags=["usage"],
    )
    def usage_summary_endpoint(
        tenant_id: str | None = None,
        consumer_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.usage_summary(
                tenant_id=tenant_id,
                consumer_id=consumer_id,
                since=since,
                until=until,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc
