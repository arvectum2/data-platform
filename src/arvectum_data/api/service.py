from __future__ import annotations

import threading
from collections.abc import Mapping

from sqlalchemy.orm import Session, sessionmaker

from ..acquisition import AcquisitionEngine
from ..billing import (
    ManualPaymentProvider,
    PaymentProvider,
)
from ..documents import TesseractOCRProvider
from ..connectors import (
    ConnectorRegistry,
)
from ..indexing import (
    BaseEmbeddingProvider,
    EmbeddingConfig,
    build_embedding_provider,
)
from ..models import ModelRouter

from ..search import (
    CrossEncoderReranker,
    HttpCrossEncoderScorer,
    SentenceTransformersCrossEncoderScorer,
)

from ..storage.postgres import (
    build_engine,
    build_session_factory,
)
from .config import Settings

from .service_support import (
    BillingAssignmentNotFound,
    BillingCatalogNotFound,
    CollectionAccessDenied,
    CollectionNotFound,
    ConnectorCredentialNotFound,
    ConsumerKeyNotFound,
    EmbeddingContractMismatch,
    EntityNotFound,
    IndexJobNotFound,
    InvoiceNotFound,
    InvoicePricingIncomplete,
    MemoryNotFound,
    PlatformNotConfigured,
    TenantQuotaExceeded,
    UnsafeUrlError,
    validate_public_http_url,
)

from .service_mixins import (
    AccessServiceMixin,
    BillingServiceMixin,
    CollectionServiceMixin,
    ExtractionServiceMixin,
    GraphServiceMixin,
    MemorySyncServiceMixin,
    RetrievalServiceMixin,
)


class DataPlatformService(
    AccessServiceMixin,
    BillingServiceMixin,
    CollectionServiceMixin,
    MemorySyncServiceMixin,
    RetrievalServiceMixin,
    GraphServiceMixin,
    ExtractionServiceMixin,
):
    def __init__(
        self,
        settings: Settings,
        *,
        session_factory: sessionmaker[Session] | None = None,
        embedding_provider: BaseEmbeddingProvider | None = None,
        acquisition: AcquisitionEngine | None = None,
        connector_registry: ConnectorRegistry | None = None,
        model_router: ModelRouter | None = None,
        payment_providers: Mapping[str, PaymentProvider] | None = None,
    ) -> None:
        self.settings = settings
        self.acquisition = acquisition
        self.connector_registry = connector_registry or self._default_connector_registry()
        self.model_router = model_router or self._build_model_router(settings)
        self.payment_providers: dict[str, PaymentProvider] = {
            ManualPaymentProvider.name: ManualPaymentProvider(),
            **dict(payment_providers or {}),
        }
        self._cross_encoder_scorer = None
        self._cross_encoder_lock = threading.Lock()
        if settings.ocr_provider == "disabled":
            self.ocr_provider = None
        elif settings.ocr_provider == "tesseract":
            self.ocr_provider = TesseractOCRProvider(
                languages=settings.ocr_languages,
                dpi=settings.ocr_dpi,
                timeout_seconds=settings.ocr_timeout_seconds,
            )
        else:
            raise ValueError(f"unsupported OCR provider {settings.ocr_provider!r}")
        self.embedding_provider = embedding_provider or build_embedding_provider(
            EmbeddingConfig(
                provider=settings.embedding_provider,
                model=settings.embedding_model,
                base_url=settings.embedding_base_url,
                timeout_seconds=settings.embedding_timeout_seconds,
                dimension=settings.embedding_dimension,
            )
        )
        if session_factory is not None:
            self.session_factory = session_factory
        elif settings.database_url.strip():
            self.session_factory = build_session_factory(build_engine(settings.database_url))
        else:
            self.session_factory = None

    def _cross_encoder_reranker(
        self,
        *,
        max_candidates: int,
    ) -> CrossEncoderReranker | None:
        provider = self.settings.cross_encoder_provider.strip().lower()
        model_name = self.settings.cross_encoder_model.strip()
        if provider == "disabled" or not model_name:
            return None
        if self._cross_encoder_scorer is None:
            with self._cross_encoder_lock:
                if self._cross_encoder_scorer is None:
                    try:
                        if provider == "http":
                            self._cross_encoder_scorer = HttpCrossEncoderScorer(
                                base_url=self.settings.cross_encoder_base_url,
                                model_name=model_name,
                                timeout_seconds=self.settings.cross_encoder_timeout_seconds,
                            )
                        elif provider == "sentence_transformers":
                            self._cross_encoder_scorer = SentenceTransformersCrossEncoderScorer(
                                model_name
                            )
                        else:
                            return None
                    except Exception:
                        return None
        return CrossEncoderReranker(
            self._cross_encoder_scorer,
            max_candidates=min(
                max_candidates,
                self.settings.cross_encoder_max_candidates,
            ),
            max_candidate_chars=self.settings.cross_encoder_max_candidate_chars,
        )


__all__ = [
    "BillingAssignmentNotFound",
    "BillingCatalogNotFound",
    "CollectionAccessDenied",
    "CollectionNotFound",
    "ConnectorCredentialNotFound",
    "ConsumerKeyNotFound",
    "DataPlatformService",
    "EmbeddingContractMismatch",
    "EntityNotFound",
    "IndexJobNotFound",
    "InvoiceNotFound",
    "InvoicePricingIncomplete",
    "MemoryNotFound",
    "PlatformNotConfigured",
    "TenantQuotaExceeded",
    "UnsafeUrlError",
    "validate_public_http_url",
]
