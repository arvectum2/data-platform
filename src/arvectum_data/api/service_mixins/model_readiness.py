from __future__ import annotations

from typing import Any


from ...models import ModelLocality, ModelPolicy, ModelRole, ModelRouter, RoleConfig

from ..config import Settings


class ModelReadinessServiceMixin:
    @staticmethod
    def _build_model_router(settings: Settings) -> ModelRouter:
        common = {
            "timeout_seconds": settings.model_timeout_seconds,
            "retry_max_attempts": settings.model_retry_max_attempts,
            "retry_base_delay_seconds": settings.model_retry_base_delay_seconds,
            "max_concurrency": settings.model_max_concurrency,
        }

        def role_config(prefix: str) -> RoleConfig:
            allowlist = tuple(
                item.strip()
                for item in getattr(settings, f"{prefix}_remote_allowlist").split(",")
                if item.strip()
            )
            version = getattr(settings, f"{prefix}_model_version").strip() or None
            return RoleConfig(
                policy=ModelPolicy(getattr(settings, f"{prefix}_policy")),
                provider=getattr(settings, f"{prefix}_provider"),
                model=getattr(settings, f"{prefix}_model"),
                version=version,
                base_url=getattr(settings, f"{prefix}_base_url"),
                locality=ModelLocality(getattr(settings, f"{prefix}_locality")),
                remote_allowlist=allowlist,
                api_key=getattr(settings, f"{prefix}_api_key"),
                **common,
            )

        return ModelRouter.build(
            reasoning=role_config("reasoning"),
            vision=role_config("vision"),
        )

    def model_status(self, *, probe: bool = False) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for role, readiness in self.model_router.readiness(probe=probe).items():
            descriptor = readiness.descriptor
            provider = self.model_router.provider(ModelRole(role))
            metrics = getattr(provider, "metrics", None)
            result[role] = {
                "enabled": readiness.enabled,
                "ready": readiness.ready,
                "provider": descriptor.provider if descriptor else None,
                "model": descriptor.model if descriptor else None,
                "version": descriptor.version if descriptor else None,
                "locality": descriptor.locality.value if descriptor else None,
                "capabilities": list(descriptor.capabilities) if descriptor else [],
                "latency_ms": readiness.latency_ms,
                "error_type": readiness.error_type,
                "metrics": (metrics.snapshot().__dict__ if metrics is not None else None),
            }
        return result
