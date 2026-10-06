from __future__ import annotations

from typing import Any


from ..acquisition.security import UnsafeURL, validate_public_url

from ..storage.postgres import (
    CollectionRow,
)

UnsafeUrlError = UnsafeURL


def validate_public_http_url(url: str) -> str:
    validate_public_url(url)
    return url


class PlatformNotConfigured(RuntimeError):
    pass


class CollectionNotFound(LookupError):
    pass


class CollectionAccessDenied(PermissionError):
    pass


class TenantQuotaExceeded(RuntimeError):
    pass


class ConsumerKeyNotFound(LookupError):
    pass


class ConnectorCredentialNotFound(LookupError):
    pass


class BillingCatalogNotFound(LookupError):
    pass


class BillingAssignmentNotFound(LookupError):
    pass


class InvoiceNotFound(LookupError):
    pass


class InvoicePricingIncomplete(ValueError):
    pass


class MemoryNotFound(LookupError):
    pass


class EntityNotFound(LookupError):
    pass


class EmbeddingContractMismatch(RuntimeError):
    pass


class IndexJobNotFound(LookupError):
    pass


def _collection_payload(row: CollectionRow) -> dict[str, Any]:
    return {
        "collection_id": row.collection_id,
        "owner": row.owner,
        "name": row.name,
        "default_language": row.default_language,
        "embedding_provider": row.embedding_provider,
        "embedding_model": row.embedding_model,
        "embedding_dimension": row.embedding_dimension,
        "active_index_revision": row.active_index_revision,
        "access_policy": dict(row.access_policy or {}),
        "retention_policy": dict(row.retention_policy or {}),
    }
