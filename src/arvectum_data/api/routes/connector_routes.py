from __future__ import annotations


from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
)

from ..schemas import (
    ConnectorCredentialCreateRequest,
    ConnectorCredentialResponse,
    ConnectorCredentialRotateRequest,
    ConnectorHealthResponse,
    DiscoveryRequest,
    DiscoveryResponse,
)

from .context import RouteContext



def register_connector_routes(router: APIRouter, context: RouteContext) -> None:
    runtime = context.runtime
    require_consumer_identity = context.require_consumer_identity
    map_service_error = context.map_service_error

    @router.post(
        "/connectors/credentials",
        response_model=ConnectorCredentialResponse,
        tags=["connectors"],
    )
    def create_connector_credential_endpoint(
        payload: ConnectorCredentialCreateRequest,
        x_arvectum_consumer: str | None = Header(default=None),
        x_arvectum_consumer_key: str | None = Header(default=None),
        runtime_service=Depends(runtime),
    ):
        consumer = require_consumer_identity(
            x_arvectum_consumer,
            x_arvectum_consumer_key,
        )
        try:
            return runtime_service.create_connector_credential(
                consumer_id=consumer,
                connector_name=payload.connector,
                secrets=payload.secrets,
                label=payload.label,
                metadata=payload.metadata,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.get(
        "/connectors/credentials",
        response_model=list[ConnectorCredentialResponse],
        tags=["connectors"],
    )
    def list_connector_credentials_endpoint(
        connector: str | None = None,
        x_arvectum_consumer: str | None = Header(default=None),
        x_arvectum_consumer_key: str | None = Header(default=None),
        runtime_service=Depends(runtime),
    ):
        consumer = require_consumer_identity(
            x_arvectum_consumer,
            x_arvectum_consumer_key,
        )
        try:
            return runtime_service.list_connector_credentials(
                consumer_id=consumer,
                connector_name=connector,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/connectors/credentials/{credential_id}/rotate",
        response_model=ConnectorCredentialResponse,
        tags=["connectors"],
    )
    def rotate_connector_credential_endpoint(
        credential_id: str,
        payload: ConnectorCredentialRotateRequest,
        x_arvectum_consumer: str | None = Header(default=None),
        x_arvectum_consumer_key: str | None = Header(default=None),
        runtime_service=Depends(runtime),
    ):
        consumer = require_consumer_identity(
            x_arvectum_consumer,
            x_arvectum_consumer_key,
        )
        try:
            return runtime_service.rotate_connector_credential(
                credential_id,
                consumer_id=consumer,
                secrets=payload.secrets,
                label=payload.label,
                metadata=payload.metadata,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/connectors/credentials/{credential_id}/revoke",
        response_model=ConnectorCredentialResponse,
        tags=["connectors"],
    )
    def revoke_connector_credential_endpoint(
        credential_id: str,
        x_arvectum_consumer: str | None = Header(default=None),
        x_arvectum_consumer_key: str | None = Header(default=None),
        runtime_service=Depends(runtime),
    ):
        consumer = require_consumer_identity(
            x_arvectum_consumer,
            x_arvectum_consumer_key,
        )
        try:
            return runtime_service.revoke_connector_credential(
                credential_id,
                consumer_id=consumer,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

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
        x_arvectum_consumer: str | None = Header(default=None),
        x_arvectum_consumer_key: str | None = Header(default=None),
        runtime_service=Depends(runtime),
    ):
        consumer = None
        if (
            payload.credential_id is not None
            or x_arvectum_consumer is not None
            or x_arvectum_consumer_key is not None
        ):
            consumer = require_consumer_identity(
                x_arvectum_consumer,
                x_arvectum_consumer_key,
            )
        try:
            discover_kwargs = {
                "connector_name": payload.connector,
                "query": payload.query,
                "cursor": payload.cursor,
                "limit": payload.limit,
            }
            if consumer is not None:
                discover_kwargs["consumer"] = consumer
            if payload.credential_id is not None:
                discover_kwargs["credential_id"] = payload.credential_id
            page = runtime_service.discover(**discover_kwargs)
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
