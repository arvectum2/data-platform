from __future__ import annotations

from typing import Any

from fastapi import (
    APIRouter,
    Depends,
)

from ...modes import MODE_PROFILES
from ...supportability import evaluate_operation_slo, overall_readiness, percentile
from ..contract import (
    CONSUMER_CONTRACT_CAPABILITIES,
    CONSUMER_CONTRACT_NAME,
    CONSUMER_CONTRACT_VERSION,
)
from ..schemas import (
    ConsumerKeyCreateRequest,
    ConsumerKeyIssuedResponse,
    ConsumerKeyResponse,
    ConsumerContractResponse,
    ExecutionModesResponse,
    StatusResponse,
)

from .context import RouteContext


def register_system_auth_routes(router: APIRouter, context: RouteContext) -> None:
    service = context.app
    runtime = context.runtime
    map_service_error = context.map_service_error

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

    @router.post(
        "/auth/consumer-keys",
        response_model=ConsumerKeyIssuedResponse,
        tags=["auth"],
    )
    def create_consumer_key(
        payload: ConsumerKeyCreateRequest,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.create_consumer_key(
                consumer_id=payload.consumer_id,
                tenant_id=payload.tenant_id,
                label=payload.label,
                expires_at=payload.expires_at,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.get(
        "/auth/consumer-keys",
        response_model=list[ConsumerKeyResponse],
        tags=["auth"],
    )
    def list_consumer_keys(
        consumer_id: str | None = None,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.list_consumer_keys(
                consumer_id=consumer_id,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/auth/consumer-keys/{key_id}/revoke",
        response_model=ConsumerKeyResponse,
        tags=["auth"],
    )
    def revoke_consumer_key(
        key_id: str,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.revoke_consumer_key(key_id)
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/auth/consumer-keys/{key_id}/rotate",
        response_model=ConsumerKeyIssuedResponse,
        tags=["auth"],
    )
    def rotate_consumer_key(
        key_id: str,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.rotate_consumer_key(key_id)
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.get(
        "/modes",
        response_model=ExecutionModesResponse,
        tags=["system"],
    )
    def execution_modes() -> ExecutionModesResponse:
        return ExecutionModesResponse(
            modes=[profile.to_dict() for profile in MODE_PROFILES.values()]
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
        payload.setdefault("metrics", {})["usage_metering_errors"] = int(
            service.state.usage_metering_errors
        )
        payload["operations"] = {}
        for name, values in service.state.operation_metrics.items():
            samples = tuple(service.state.operation_latency_samples[name])
            operation_payload = dict(values)
            operation_payload["window_samples"] = len(samples)
            operation_payload["p95_ms"] = percentile(samples, 0.95)
            payload["operations"][name] = operation_payload
        return payload

    @router.get("/support/readiness", tags=["system"])
    def support_readiness() -> dict[str, Any]:
        operations = {
            name: evaluate_operation_slo(
                operation=name,
                requests=int(values["requests"]),
                errors=int(values["errors"]),
                latency_samples_ms=tuple(service.state.operation_latency_samples[name]),
            )
            for name, values in service.state.operation_metrics.items()
        }
        return {
            "status": overall_readiness(operations),
            "window_size": 256,
            "operations": operations,
        }

    @router.get("/models/status", tags=["system"])
    def model_status(
        probe: bool = False,
        runtime_service=Depends(runtime),
    ) -> dict[str, dict[str, Any]]:
        if not hasattr(runtime_service, "model_status"):
            return {}
        return runtime_service.model_status(probe=probe)
