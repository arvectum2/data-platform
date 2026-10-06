# Usage metering

DP-METER-001 provides durable, content-free accounting for authenticated external consumers. It is the billing substrate for a future external Data Platform product; pricing, invoices and payment-provider integration stay outside the platform core.

## What is metered

The HTTP layer meters authenticated consumer requests for:

- search;
- answer synthesis;
- research;
- discovery for authenticated consumers;
- memory write;
- memory delete.

Internal-only control-plane traffic is not billed by this meter. Authenticated consumer discovery is metered now that customer-managed connector credentials are supported. Customer ingest remains internal until an external ingest contract is explicitly introduced.

Each event stores only:

- tenant ID when one is bound to the consumer;
- consumer ID;
- normalized operation;
- unit and quantity;
- HTTP status;
- whether the event is billable;
- request ID;
- numeric duration and request-byte metadata;
- timestamp.

Query text, URLs, document content, search results, credentials and model prompts are never stored in usage events.

## Billable semantics

A successful 2xx/3xx authenticated data-plane request is marked billable. Auth failures are not recorded because the claimed consumer identity is not trusted. Other authenticated failures may be recorded as non-billable events so operators can distinguish demand from successful usage.

The current meter is request-based (`unit=request`, `quantity=1`). The schema deliberately keeps `unit` and `quantity` explicit so later product pricing can add separately governed meters without changing historical events.

## Idempotency

Usage event IDs are deterministic over:

`consumer_id + request_id + operation + unit`

The database also enforces the same identity as a unique constraint. Retrying the same request with the same `X-Request-ID` therefore does not double-count usage.

## Failure behavior

Metering is fail-open for the user-facing data plane. A storage/metering failure never converts a successful search into an outage. `/v1/status` exposes `metrics.usage_metering_errors` so a broken billing pipeline is visible and can be alerted on.

This is intentionally different from authorization and tenant isolation, which remain fail-closed.

## Summary API

Internal operators can query:

`GET /v1/usage/summary`

Optional filters:

- `tenant_id`;
- `consumer_id`;
- `since`;
- `until`.

The response is aggregate-only. It returns event count, total quantity, billable quantity and buckets grouped by tenant, consumer, operation and unit. There is no raw-event endpoint in v1.

## Billing boundary

Data Platform now owns trustworthy usage accounting, but not commercial policy. Product pricing, currency, taxes, invoice generation, credits, plan changes and payment-provider integration belong to the external product/billing layer.

This separation keeps historical usage immutable when commercial pricing changes.

## Production acceptance — 2026-10-06

Migration `0010_usage_events` was applied to the production `arvectum_data` PostgreSQL database and the API was restarted on the merged DP-METER-001 build.

A live authenticated `growth-agent` search was sent twice with the same `X-Request-ID`. Both requests returned HTTP 200 with three hits, while the durable usage total changed from 0 to 1 and billable quantity changed by exactly +1. This verifies retry deduplication in the production path.

The stored event contained only consumer/operation/accounting fields plus numeric metadata (`duration_ms` and `request_bytes`); no query text, URL, result content, prompt or credential was persisted. `/v1/status` reported `usage_metering_errors=0` after the smoke.
