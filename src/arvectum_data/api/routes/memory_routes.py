from __future__ import annotations


from fastapi import (
    APIRouter,
    Depends,
    Header,
)

from ..schemas import (
    MemoryWriteRequest,
    MemoryWriteResponse,
)

from .context import RouteContext



def register_memory_routes(router: APIRouter, context: RouteContext) -> None:
    runtime = context.runtime
    require_consumer_identity = context.require_consumer_identity
    map_service_error = context.map_service_error

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
