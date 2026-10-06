from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from ..api.config import Settings


@dataclass(frozen=True, slots=True)
class PrivateComponent:
    component: str
    private: bool
    mode: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "private": self.private,
            "mode": self.mode,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class PrivateRuntimeReport:
    scope: str
    components: tuple[PrivateComponent, ...]

    @property
    def coverage(self) -> float:
        return sum(1 for item in self.components if item.private) / len(self.components)

    @property
    def fully_private(self) -> bool:
        return all(item.private for item in self.components)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "coverage": self.coverage,
            "fully_private": self.fully_private,
            "components": [item.to_dict() for item in self.components],
        }


def _loopback_host(value: str) -> bool:
    cleaned = value.strip()
    if not cleaned:
        return False
    if cleaned == "localhost":
        return True
    try:
        return ipaddress.ip_address(cleaned).is_loopback
    except ValueError:
        return False


def _url_is_loopback(value: str) -> bool:
    cleaned = value.strip()
    if not cleaned:
        return False
    parsed = urlsplit(cleaned)
    if parsed.scheme.startswith("sqlite"):
        return True
    return _loopback_host(parsed.hostname or "")


def _role_component(
    name: str,
    *,
    policy: str,
    locality: str,
    base_url: str,
) -> PrivateComponent:
    normalized_policy = policy.strip().lower()
    if normalized_policy == "disabled":
        return PrivateComponent(name, True, "disabled", "capability disabled")
    if (
        normalized_policy == "local-only"
        and locality.strip().lower() == "local"
        and _url_is_loopback(base_url)
    ):
        return PrivateComponent(
            name,
            True,
            "local-only",
            "local-only policy with loopback endpoint",
        )
    return PrivateComponent(
        name,
        False,
        normalized_policy or "unknown",
        "role is not constrained to a local loopback endpoint",
    )


def evaluate_private_runtime(settings: Settings) -> PrivateRuntimeReport:
    components: list[PrivateComponent] = [
        PrivateComponent(
            "api",
            _loopback_host(settings.host),
            "loopback" if _loopback_host(settings.host) else "network",
            "service bind address",
        ),
        PrivateComponent(
            "database",
            _url_is_loopback(settings.database_url),
            "local" if _url_is_loopback(settings.database_url) else "remote",
            "database hostname is loopback/local",
        ),
    ]

    embedding_provider = settings.embedding_provider.strip().lower()
    embedding_private = (
        embedding_provider == "hashing"
        or _url_is_loopback(settings.embedding_base_url)
    )
    components.append(
        PrivateComponent(
            "embeddings",
            embedding_private,
            "in-process" if embedding_provider == "hashing" else "loopback",
            "embedding provider executes locally",
        )
    )

    ocr_provider = settings.ocr_provider.strip().lower()
    ocr_private = ocr_provider in {"disabled", "tesseract"}
    components.append(
        PrivateComponent(
            "ocr",
            ocr_private,
            ocr_provider or "unknown",
            "OCR is disabled or uses local Tesseract",
        )
    )

    components.append(
        _role_component(
            "reasoning",
            policy=settings.reasoning_policy,
            locality=settings.reasoning_locality,
            base_url=settings.reasoning_base_url,
        )
    )
    components.append(
        _role_component(
            "vision",
            policy=settings.vision_policy,
            locality=settings.vision_locality,
            base_url=settings.vision_base_url,
        )
    )

    return PrivateRuntimeReport(
        scope=(
            "core ingestion/OCR/indexing/retrieval/reasoning pipeline; "
            "external discovery/acquisition connectors excluded"
        ),
        components=tuple(components),
    )
