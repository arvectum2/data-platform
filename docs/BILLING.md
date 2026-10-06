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

A concrete YooKassa adapter is available for RUB online payments. It supports the provider's smart-payment flow or explicit SBP, uses HTTP Basic authentication at the provider boundary, sends a deterministic invoice-derived idempotence key on payment creation, requests automatic capture and returns the provider confirmation URL. Runtime activation still requires merchant credentials to be supplied through an approved secret channel.

## YooKassa reconciliation

The adapter never marks an invoice paid from an unverified callback payload. `sync_invoice_payment` fetches the current payment object from YooKassa and verifies:

- the provider payment reference matches the invoice handoff;
- returned currency matches the invoice;
- returned amount in minor units matches the invoice total;
- payment status is `succeeded` and the provider reports it paid.

Only then is the invoice moved to `paid`. Canceled or pending provider states remain separate `provider_status` values while the invoice remains finalized.

The adapter is hard-wired to the official YooKassa API base URL by default; runtime configuration does not expose an arbitrary credential destination. Unit tests can inject a fake HTTPS base URL directly into the provider class.

Webhook handling can use the same reconciliation path: receive the event, extract the payment reference, then fetch current payment state from the provider before mutating invoice state. Live webhook/provider activation remains blocked until merchant credentials are deliberately supplied.

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
- `POST /v1/billing/invoices/{invoice_id}/sync-payment`;
- `POST /v1/billing/invoices/{invoice_id}/mark-paid`.

These surfaces are intentionally not exposed through consumer credentials.

## Production schema status — 2026-10-06

Migrations `0012_billing_pricing_invoices` and `0013_invoice_provider_status` are applied in production. The Data Platform API restarted healthy on the merged billing/YooKassa builds.

No YooKassa merchant credentials are configured or inferred from the host. Therefore the provider adapter is installed but not active in the production provider registry; live payment creation/reconciliation remains blocked on an explicitly supplied merchant secret through an approved runtime channel.

## Production billing-core acceptance — 2026-10-06

Migrations through `0013_invoice_provider_status` are applied in production. A dedicated acceptance tenant was used to exercise the complete provider-neutral billing lifecycle without external merchant credentials.

The acceptance catalog used RUB minor units, a 10000 base fee, one included search request, 250 per additional search request and 1000 per research request. Two billable search events plus one billable research event produced a preview total of 11250 with no unpriced usage. The line amounts were 250 for search and 1000 for research.

Finalization created one invoice with a 64-character usage snapshot hash. Repeating finalization for the same tenant and period returned the same invoice ID, confirming idempotence. Manual payment handoff produced a `manual:` provider reference, and the invoice was then marked paid with a paid timestamp present.

No YooKassa or other external merchant credential was used or discovered during this acceptance.
