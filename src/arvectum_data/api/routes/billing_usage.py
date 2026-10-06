from __future__ import annotations

from datetime import datetime

from fastapi import (
    APIRouter,
    Depends,
)

from ..schemas import (
    TenantBillingAssignmentResponse,
    TenantBillingAssignRequest,
    InvoiceResponse,
    InvoicePeriodRequest,
    InvoiceMarkPaidRequest,
    BillingCatalogResponse,
    BillingCatalogCreateRequest,
    UsageSummaryResponse,
)

from .context import RouteContext


def register_billing_usage_routes(router: APIRouter, context: RouteContext) -> None:
    runtime = context.runtime
    map_service_error = context.map_service_error

    @router.post(
        "/billing/catalogs",
        response_model=BillingCatalogResponse,
        tags=["billing"],
    )
    def create_billing_catalog_endpoint(
        payload: BillingCatalogCreateRequest,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.create_billing_catalog(
                plan_code=payload.plan_code,
                version=payload.version,
                name=payload.name,
                currency=payload.currency,
                base_fee_minor=payload.base_fee_minor,
                rules=[item.model_dump() for item in payload.rules],
                effective_from=payload.effective_from,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.get(
        "/billing/catalogs",
        response_model=list[BillingCatalogResponse],
        tags=["billing"],
    )
    def list_billing_catalogs_endpoint(
        plan_code: str | None = None,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.list_billing_catalogs(plan_code=plan_code)
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/billing/tenants/{tenant_id}/assignments",
        response_model=TenantBillingAssignmentResponse,
        tags=["billing"],
    )
    def assign_tenant_billing_endpoint(
        tenant_id: str,
        payload: TenantBillingAssignRequest,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.assign_tenant_billing(
                tenant_id=tenant_id,
                catalog_id=payload.catalog_id,
                effective_from=payload.effective_from,
                payment_provider=payload.payment_provider,
                external_customer_id=payload.external_customer_id,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.get(
        "/billing/tenants/{tenant_id}/assignments",
        response_model=list[TenantBillingAssignmentResponse],
        tags=["billing"],
    )
    def list_tenant_billing_assignments_endpoint(
        tenant_id: str,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.list_tenant_billing_assignments(
                tenant_id=tenant_id,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/billing/invoices/preview",
        response_model=InvoiceResponse,
        tags=["billing"],
    )
    def preview_invoice_endpoint(
        payload: InvoicePeriodRequest,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.preview_invoice(
                tenant_id=payload.tenant_id,
                period_start=payload.period_start,
                period_end=payload.period_end,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/billing/invoices/finalize",
        response_model=InvoiceResponse,
        tags=["billing"],
    )
    def finalize_invoice_endpoint(
        payload: InvoicePeriodRequest,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.finalize_invoice(
                tenant_id=payload.tenant_id,
                period_start=payload.period_start,
                period_end=payload.period_end,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.get(
        "/billing/invoices",
        response_model=list[InvoiceResponse],
        tags=["billing"],
    )
    def list_invoices_endpoint(
        tenant_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.list_invoices(
                tenant_id=tenant_id,
                status=status,
                limit=limit,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.get(
        "/billing/invoices/{invoice_id}",
        response_model=InvoiceResponse,
        tags=["billing"],
    )
    def get_invoice_endpoint(
        invoice_id: str,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.get_invoice(invoice_id)
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/billing/invoices/{invoice_id}/payment",
        response_model=InvoiceResponse,
        tags=["billing"],
    )
    def create_invoice_payment_endpoint(
        invoice_id: str,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.create_invoice_payment(invoice_id)
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/billing/invoices/{invoice_id}/sync-payment",
        response_model=InvoiceResponse,
        tags=["billing"],
    )
    def sync_invoice_payment_endpoint(
        invoice_id: str,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.sync_invoice_payment(invoice_id)
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/billing/invoices/{invoice_id}/mark-paid",
        response_model=InvoiceResponse,
        tags=["billing"],
    )
    def mark_invoice_paid_endpoint(
        invoice_id: str,
        payload: InvoiceMarkPaidRequest,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.mark_invoice_paid(
                invoice_id,
                provider_reference=payload.provider_reference,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.get(
        "/usage/summary",
        response_model=UsageSummaryResponse,
        tags=["usage"],
    )
    def usage_summary_endpoint(
        tenant_id: str | None = None,
        consumer_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.usage_summary(
                tenant_id=tenant_id,
                consumer_id=consumer_id,
                since=since,
                until=until,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc
