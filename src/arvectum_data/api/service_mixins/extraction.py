from __future__ import annotations

from collections.abc import Mapping, Sequence


from ...acquisition.security import validate_public_url
from ...engine import (
    AutoDiscoveryProvider,
    ExtractionEngine,
    FieldSpec,
    RawAsset,
    ReasoningCandidateProvider,
)
from ...orchestration import URLExtractionPipeline
from ...models import ModelRole


class ExtractionServiceMixin:
    def _extraction_providers(self, use_model: bool):
        providers = [AutoDiscoveryProvider()]
        if use_model:
            reasoning = self.model_router.provider(ModelRole.REASONING)
            if reasoning is not None:
                providers.append(ReasoningCandidateProvider(reasoning))
        return tuple(providers)

    def extract_url(
        self,
        *,
        url: str,
        fields: Sequence[FieldSpec],
        use_model: bool = False,
    ):
        if not self.settings.allow_private_fetches:
            validate_public_url(url)
        pipeline = URLExtractionPipeline(
            acquisition=self.acquisition,
            providers=self._extraction_providers(use_model),
        )
        return pipeline.extract_url(url, fields)

    def extract(
        self,
        *,
        asset_id: str,
        source_url: str | None,
        text: str | None,
        html: str | None,
        attributes: Mapping[str, object],
        fields: Sequence[FieldSpec],
        use_model: bool = False,
    ):
        engine = ExtractionEngine(self._extraction_providers(use_model))
        asset = RawAsset(
            asset_id=asset_id,
            source_url=source_url,
            text=text,
            html=html,
            attributes=dict(attributes),
        )
        return engine.extract(asset, fields)
