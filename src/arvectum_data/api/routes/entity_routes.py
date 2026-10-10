from __future__ import annotations


from fastapi import (
    APIRouter,
    Depends,
)

from ..schemas import (
    EntityCreateRequest,
    EntityRelationCreateRequest,
    EntityRelationResponse,
    EntityResolveRequest,
    EntityResolveResponse,
    EntityResponse,
)

from .context import RouteContext




def register_entity_routes(router: APIRouter, context: RouteContext) -> None:
    runtime = context.runtime
    map_service_error = context.map_service_error

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
                status=payload.status,
                valid_from=payload.valid_from,
                valid_to=payload.valid_to,
                source_collection_id=payload.source_collection_id,
                resource_id=payload.resource_id,
                document_id=payload.document_id,
                chunk_id=payload.chunk_id,
                metadata=payload.metadata,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc
