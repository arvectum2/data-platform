from __future__ import annotations


from fastapi import (
    APIRouter,
    Depends,
)

from ..schemas import (
    CollectionCreateRequest,
    CollectionDeleteResponse,
    CollectionExportResponse,
    CollectionResponse,
    CollectionRetentionPruneResponse,
    CollectionStatsResponse,
)

from .context import RouteContext



def register_collection_routes(router: APIRouter, context: RouteContext) -> None:
    runtime = context.runtime
    map_service_error = context.map_service_error

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
                    None if payload.access_policy is None else payload.access_policy.model_dump(exclude_none=True)
                ),
                retention_policy=(
                    None
                    if payload.retention_policy is None
                    else payload.retention_policy.model_dump(exclude_none=True)
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
        "/collections/{collection_id}/export",
        response_model=CollectionExportResponse,
        tags=["collections"],
    )
    def export_collection(
        collection_id: str,
        include_content: bool = False,
        offset: int = 0,
        limit: int = 100,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.export_collection(
                collection_id,
                include_content=include_content,
                offset=offset,
                limit=limit,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/collections/{collection_id}/retention/prune",
        response_model=CollectionRetentionPruneResponse,
        tags=["collections"],
    )
    def prune_collection_retention(
        collection_id: str,
        dry_run: bool = True,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.prune_collection_retention(
                collection_id,
                dry_run=dry_run,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.delete(
        "/collections/{collection_id}",
        response_model=CollectionDeleteResponse,
        tags=["collections"],
    )
    def delete_collection(
        collection_id: str,
        confirm: bool = False,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.delete_collection(
                collection_id,
                confirm=confirm,
            )
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
