from __future__ import annotations

from typing import Protocol

from ..acquisition import AcquisitionResult
from .models import ConnectorHealth, DiscoveryPage, DiscoveredResource


class DiscoveryConnector(Protocol):
    name: str

    def discover(
        self,
        query: str,
        *,
        cursor: str | None = None,
        limit: int = 10,
    ) -> DiscoveryPage: ...

    def health(self) -> ConnectorHealth: ...


class FetchConnector(Protocol):
    name: str

    def fetch(self, resource: DiscoveredResource) -> AcquisitionResult: ...

    def health(self) -> ConnectorHealth: ...


class Connector(DiscoveryConnector, FetchConnector, Protocol):
    pass
