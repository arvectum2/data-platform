from __future__ import annotations

from pathlib import Path
from typing import Any


from ...connectors import (
    ConnectorRegistry,
    DiscoveredResource,
    DuckDuckGoHTMLConnector,
    GitHubRepositoryConnector,
    ManualURLConnector,
    SitemapConnector,
)

from ...storage.postgres import (
    CollectionRow,
)


from ..service_support import (
    CollectionNotFound,
    CollectionAccessDenied,
)


class ConnectorDiscoveryServiceMixin:
    @staticmethod
    def _default_connector_registry() -> ConnectorRegistry:
        registry = ConnectorRegistry()
        registry.register(ManualURLConnector())
        registry.register(SitemapConnector())
        registry.register(DuckDuckGoHTMLConnector())
        registry.register(GitHubRepositoryConnector())
        return registry

    def connector_status(self) -> list[dict[str, Any]]:
        return [
            {
                "name": item.name,
                "state": item.state.value,
                "capabilities": list(item.capabilities),
                "detail": item.detail,
                "metadata": dict(item.metadata),
            }
            for item in self.connector_registry.health()
        ]

    def _connector_for_request(
        self,
        connector_name: str,
        *,
        consumer: str | None = None,
        credential_id: str | None = None,
    ):
        connector = self.connector_registry.get(connector_name)
        if credential_id is None:
            return connector
        if consumer is None:
            raise CollectionAccessDenied("connector credential requires consumer identity")
        credential = self.resolve_connector_credential(
            credential_id,
            consumer_id=consumer,
            connector_name=connector_name,
        )
        configure = getattr(connector, "with_credentials", None)
        if configure is None:
            raise ValueError(f"connector {connector_name!r} does not support managed credentials")
        return configure(
            credential["secrets"],
            metadata=credential["metadata"],
        )

    def discover(
        self,
        *,
        connector_name: str,
        query: str,
        cursor: str | None = None,
        limit: int = 10,
        consumer: str | None = None,
        credential_id: str | None = None,
    ):
        connector = self._connector_for_request(
            connector_name,
            consumer=consumer,
            credential_id=credential_id,
        )
        discover = getattr(connector, "discover", None)
        if discover is None:
            raise ValueError(f"connector {connector_name!r} does not support discovery")
        return discover(query, cursor=cursor, limit=limit)

    def ingest_discovered_resource(
        self,
        *,
        collection_id: str,
        connector_name: str,
        resource: DiscoveredResource,
        consumer: str | None = None,
        credential_id: str | None = None,
    ) -> dict[str, Any]:
        with self._require_factory()() as session:
            collection = session.get(CollectionRow, collection_id)
            if collection is None:
                raise CollectionNotFound(collection_id)
            self._authorize_collection_consumer(
                collection,
                consumer,
                session=session,
            )

        connector = self._connector_for_request(
            connector_name,
            consumer=consumer,
            credential_id=credential_id,
        )
        fetch = getattr(connector, "fetch", None)
        if fetch is None:
            raise ValueError(f"connector {connector_name!r} does not support fetch")
        acquired = fetch(resource)
        asset = acquired.asset
        if asset.html is not None:
            content = asset.html.encode("utf-8")
            filename = str(resource.metadata.get("path") or resource.title or "resource.html")
            if not Path(filename).suffix:
                filename += ".html"
        else:
            content = (asset.text or "").encode("utf-8")
            filename = str(resource.metadata.get("path") or resource.title or "resource.txt")
            if not Path(filename).suffix:
                filename += ".txt"
        return self.ingest_document_bytes(
            collection_id=collection_id,
            filename=filename,
            content=content,
            title=resource.title,
            canonical_uri=resource.canonical_uri,
        )
