# Pricing, invoicing and payment handoff

DP-BILL-001 turns durable usage metering into immutable billing artifacts without embedding commercial policy into usage history.

## Price catalogs

A price catalog is immutable after creation and contains:

- plan code and integer version;
- display name;
- three-letter currency code;
- base fee in minor currency units;
- meter rules keyed by operation + unit;
- included quantity and unit price in minor units;
- effective-from timestamp.

Changing prices means creating a new catalog version. Historical catalogs are never rewritten.

## Tenant assignments

Tenant assignments are versioned intervals rather than a mutable current-plan field. Assigning a new catalog closes the prior interval and opens a new one.

An invoice period must be covered by one assignment for the entire interval. If a tariff changes inside the requested period, preview/finalize fails instead of silently blending prices.

## Invoice calculation

Only billable DP-METER-001 events participate in invoices. Usage is aggregated across consumers by tenant + operation + unit.

For each priced meter:

`chargeable = max(0, billable_quantity - included_quantity)`

`amount_minor = chargeable * unit_price_minor`

The catalog base fee is then added. Monetary arithmetic uses integer minor units only.

Preview returns explicit unpriced usage. Finalization fails closed while any billable meter lacks a price rule, preventing silent underbilling.

## Immutable invoice snapshot

Finalization stores:

- tenant and billing period;
- catalog ID plus a complete pricing snapshot;
- deterministic hash of the ordered billable usage events;
- calculated lines and totals;
- payment-provider selection;
- finalized timestamp.

The `(tenant, period_start, period_end)` database constraint makes finalization idempotent for one billing period. Repeating finalize returns the existing invoice.

Later catalog changes do not alter finalized invoices.

## Payment provider boundary

`PaymentProvider` is provider-neutral. A provider receives only invoice ID, tenant ID, currency, amount and a bounded description, and returns a provider reference plus an optional payment URL.

The built-in `manual` provider supports invoice lifecycle testing and offline/bank-transfer workflows. Payment handoff itself is idempotent: an invoice with a provider reference is not submitted again.

`mark-paid` is an internal administrative action and records the paid timestamp and optional provider/bank reference.

A concrete online acquiring/СБП adapter remains a separate product integration because provider credentials, webhook signatures, fiscalization/tax requirements and commercial terms are provider-specific and can change independently of Data Platform.

## Control-plane API

Internal-key-only endpoints:

- `POST /v1/billing/catalogs`;
- `GET /v1/billing/catalogs`;
- `POST /v1/billing/tenants/{tenant_id}/assignments`;
- `GET /v1/billing/tenants/{tenant_id}/assignments`;
- `POST /v1/billing/invoices/preview`;
- `POST /v1/billing/invoices/finalize`;
- `GET /v1/billing/invoices`;
- `GET /v1/billing/invoices/{invoice_id}`;
- `POST /v1/billing/invoices/{invoice_id}/payment`;
- `POST /v1/billing/invoices/{invoice_id}/mark-paid`.

These surfaces are intentionally not exposed through consumer credentials.
