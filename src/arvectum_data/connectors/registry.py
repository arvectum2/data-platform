from __future__ import annotations

from .models import ConnectorHealth


class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, object] = {}

    def register(self, connector: object) -> None:
        name = str(getattr(connector, "name", "")).strip()
        if not name:
            raise ValueError("connector.name must not be blank")
        if name in self._connectors:
            raise ValueError(f"connector {name!r} is already registered")
        self._connectors[name] = connector

    def replace(self, connector: object) -> None:
        name = str(getattr(connector, "name", "")).strip()
        if not name:
            raise ValueError("connector.name must not be blank")
        self._connectors[name] = connector

    def get(self, name: str):
        try:
            return self._connectors[name]
        except KeyError as exc:
            raise KeyError(f"unknown connector: {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._connectors))

    def health(self) -> tuple[ConnectorHealth, ...]:
        results = []
        for name in self.names():
            connector = self._connectors[name]
            health = getattr(connector, "health", None)
            if health is None:
                continue
            results.append(health())
        return tuple(results)
