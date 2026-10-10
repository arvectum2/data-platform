from __future__ import annotations


from fastapi import (
    APIRouter,
    Depends,
)

from ..schemas import (
    RefreshPolicyRequest,
    RefreshPolicyResponse,
    RefreshResultResponse,
    RefreshRunResponse,
)

from .context import RouteContext



def register_refresh_routes(router: APIRouter, context: RouteContext) -> None:
    runtime = context.runtime
    map_service_error = context.map_service_error

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
