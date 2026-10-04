from __future__ import annotations

from ..acquisition import AcquisitionEngine, AcquisitionRequest, AcquisitionResult, RenderMode
from ..acquisition.security import validate_public_url
from .http import PublicHTTPTransport
from .models import ConnectorHealth, ConnectorPolicy, ConnectorState, DiscoveryPage, DiscoveredResource
from .policy import ConnectorExecutor


class ManualURLConnector:
    name = "manual_url"

    def __init__(
        self,
        *,
        acquisition: AcquisitionEngine | None = None,
        policy: ConnectorPolicy | None = None,
    ) -> None:
        self.acquisition = acquisition or AcquisitionEngine(
            http=PublicHTTPTransport(),
            renderer=None,
        )
        self.executor = ConnectorExecutor(policy)

    def discover(
        self,
        query: str,
        *,
        cursor: str | None = None,
        limit: int = 10,
    ) -> DiscoveryPage:
        if cursor is not None:
            return DiscoveryPage(resources=())
        validate_public_url(query)
        if limit < 1:
            return DiscoveryPage(resources=())
        return DiscoveryPage(
            resources=(
                DiscoveredResource(
                    canonical_uri=query,
                    provider=self.name,
                    source_type="url",
                    rank=1,
                ),
            )
        )

    def fetch(self, resource: DiscoveredResource) -> AcquisitionResult:
        validate_public_url(resource.canonical_uri)
        return self.executor.run(
            lambda: self.acquisition.acquire(
                AcquisitionRequest(
                    url=resource.canonical_uri,
                    render_mode=RenderMode.NEVER,
                )
            )
        )

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(
            name=self.name,
            state=ConnectorState.READY,
            capabilities=("discover", "fetch"),
            detail="public HTTP(S) manual URL connector",
        )
