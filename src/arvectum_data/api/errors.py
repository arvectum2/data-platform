from __future__ import annotations

from fastapi import HTTPException
from ..acquisition.security import UnsafeURL
from .service import (
    CollectionAccessDenied,
    InvoicePricingIncomplete,
    InvoiceNotFound,
    BillingCatalogNotFound,
    BillingAssignmentNotFound,
    CollectionNotFound,
    ConnectorCredentialNotFound,
    ConsumerKeyNotFound,
    EmbeddingContractMismatch,
    EntityNotFound,
    IndexJobNotFound,
    MemoryNotFound,
    PlatformNotConfigured,
    TenantQuotaExceeded,
)

def map_service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PlatformNotConfigured):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, CollectionNotFound):
        return HTTPException(status_code=404, detail="collection not found")
    if isinstance(exc, ConsumerKeyNotFound):
        return HTTPException(status_code=404, detail="consumer key not found")
    if isinstance(exc, ConnectorCredentialNotFound):
        return HTTPException(status_code=404, detail="connector credential not found")
    if isinstance(exc, BillingCatalogNotFound):
        return HTTPException(status_code=404, detail="billing catalog not found")
    if isinstance(exc, BillingAssignmentNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, InvoiceNotFound):
        return HTTPException(status_code=404, detail="invoice not found")
    if isinstance(exc, InvoicePricingIncomplete):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, CollectionAccessDenied):
        return HTTPException(status_code=403, detail="collection access denied")
    if isinstance(exc, TenantQuotaExceeded):
        return HTTPException(status_code=429, detail=str(exc))
    if isinstance(exc, IndexJobNotFound):
        return HTTPException(status_code=404, detail="index job not found")
    if isinstance(exc, MemoryNotFound):
        return HTTPException(status_code=404, detail="memory not found")
    if isinstance(exc, EntityNotFound):
        return HTTPException(status_code=404, detail="entity not found")
    if isinstance(exc, (EmbeddingContractMismatch, UnsafeURL, ValueError)):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="internal data platform error")
