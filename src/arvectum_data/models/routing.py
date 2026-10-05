from __future__ import annotations

from dataclasses import dataclass, field
import ipaddress
from urllib.parse import urlparse

from .models import ModelLocality, ModelPolicy, ModelRole, ProviderReadiness
from .providers import OpenAICompatibleProvider, TextGenerationProvider, VisionProvider


@dataclass(frozen=True)
class RoleConfig:
    policy: ModelPolicy = ModelPolicy.DISABLED
    provider: str = "openai-compatible"
    model: str = ""
    version: str | None = None
    base_url: str = ""
    locality: ModelLocality = ModelLocality.LOCAL
    remote_allowlist: tuple[str, ...] = ()
    timeout_seconds: float = 60
    retry_max_attempts: int = 2
    retry_base_delay_seconds: float = 0.25
    max_concurrency: int = 2
    api_key: str = ""


@dataclass
class ModelRouter:
    providers: dict[ModelRole, TextGenerationProvider | VisionProvider] = field(default_factory=dict)

    @classmethod
    def build(cls, *, reasoning: RoleConfig, vision: RoleConfig) -> "ModelRouter":
        router = cls()
        router._configure(ModelRole.REASONING, reasoning)
        router._configure(ModelRole.VISION, vision)
        return router

    def _configure(self, role: ModelRole, config: RoleConfig) -> None:
        if config.policy == ModelPolicy.DISABLED:
            return
        if config.policy == ModelPolicy.LOCAL_ONLY:
            if config.locality != ModelLocality.LOCAL:
                raise ValueError(f"{role.value}: local-only policy rejects remote provider")
            hostname = (urlparse(config.base_url).hostname or "").lower()
            try:
                is_loopback = ipaddress.ip_address(hostname).is_loopback
            except ValueError:
                is_loopback = hostname == "localhost"
            if not is_loopback:
                raise ValueError(f"{role.value}: local-only policy requires a loopback endpoint")
        if config.locality == ModelLocality.REMOTE:
            if config.policy != ModelPolicy.REMOTE_ALLOWLIST:
                raise ValueError(f"{role.value}: remote provider requires remote-allowlist policy")
            hostname = (urlparse(config.base_url).hostname or "").lower()
            if hostname not in config.remote_allowlist:
                raise ValueError(f"{role.value}: remote endpoint is not in the allowlist")
        if config.provider != "openai-compatible":
            raise ValueError(f"{role.value}: unsupported model provider {config.provider!r}")
        if not config.model or not config.base_url:
            raise ValueError(f"{role.value}: enabled provider requires model and base_url")
        self.providers[role] = OpenAICompatibleProvider(role=role, model=config.model, version=config.version, base_url=config.base_url, locality=config.locality, timeout_seconds=config.timeout_seconds, retry_max_attempts=config.retry_max_attempts, retry_base_delay_seconds=config.retry_base_delay_seconds, max_concurrency=config.max_concurrency, api_key=config.api_key)

    def provider(self, role: ModelRole):
        return self.providers.get(role)

    def readiness(self, *, probe: bool = False) -> dict[str, ProviderReadiness]:
        result: dict[str, ProviderReadiness] = {}
        for role in ModelRole:
            provider = self.providers.get(role)
            if provider is None:
                result[role.value] = ProviderReadiness(False, False, None)
            elif probe:
                result[role.value] = provider.probe()
            else:
                result[role.value] = ProviderReadiness(True, True, provider.descriptor)
        return result
