from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ModelRole(StrEnum):
    REASONING = "reasoning"
    VISION = "vision"


class ModelLocality(StrEnum):
    LOCAL = "local"
    REMOTE = "remote"


class ModelPolicy(StrEnum):
    DISABLED = "disabled"
    LOCAL_ONLY = "local-only"
    REMOTE_ALLOWLIST = "remote-allowlist"


@dataclass(frozen=True)
class ModelDescriptor:
    role: ModelRole
    provider: str
    model: str
    version: str | None
    locality: ModelLocality
    capabilities: tuple[str, ...]


@dataclass(frozen=True)
class GenerationRequest:
    prompt: str
    system_prompt: str | None = None
    max_tokens: int = 1024
    temperature: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VisionRequest:
    prompt: str
    image_url: str
    system_prompt: str | None = None
    max_tokens: int = 1024
    temperature: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelResponse:
    text: str
    provider: str
    model: str
    version: str | None
    locality: ModelLocality
    latency_ms: float
    usage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderReadiness:
    enabled: bool
    ready: bool
    descriptor: ModelDescriptor | None
    latency_ms: float | None = None
    error_type: str | None = None
