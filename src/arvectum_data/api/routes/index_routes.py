from __future__ import annotations


from fastapi import (
    APIRouter,
    Depends,
)

from ..schemas import (
    IndexJobResponse,
    IndexRebuildRequest,
)

from .context import RouteContext



def register_index_routes(router: APIRouter, context: RouteContext) -> None:
    runtime = context.runtime
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
