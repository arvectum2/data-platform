# Refactor Phase 5 — bounded billing memory, invoice batch reads and usage idempotency

**Base:** PR #91 (bounded embeddings and federated SQL), itself tested against the preceding Data Platform refactor. No live service restarts, production database writes or migrations in this phase.

## `api.service_mixins.billing` audit and changes

1. **Invoice preview memory:** `_preview_invoice_in_session` previously loaded every ORM `UsageEventRow`, including entire metadata JSON values, and built a second list plus a giant joined string to compute the SHA-256 snapshot. It now selects only `usage_event_id`, `operation`, `unit`, and `quantity`, streams cursor rows with `yield_per=1000` and updates the digest incrementally using **exactly the same bytes and ordering** as the historical `"\\n".join(...)` algorithm. The existing `UsageQuantity` aggregation and price calculations are unchanged. Empty input hashes to SHA-256 of empty bytes as before.
2. **Invoice list N+1:** `list_invoices` selected one page of invoices and ran one SELECT for each invoice's lines, up to 501 SELECTs for a 500-invoice page. It now prefetches lines for that page in a single `IN(invoice_id)` SELECT, preserving line ordering and response shape: **2 SELECTs regardless of page length**. `get_invoice` and single-invoice payment endpoints retain their existing paths.
3. **Concurrent usage events:** The original `record_usage_event` checked existence before INSERT but could still raise a unique-key conflict under simultaneous worker requests. It now uses PostgreSQL `ON CONFLICT DO NOTHING` on the stable event ID, then retrieves the original immutable record. Historical quantity, billable status, request identity, timestamp and metadata are never overwritten on replay. No duplicated billable event can be inserted under concurrent calls.

## Verification

- Real PostgreSQL invoice regression: six distinct invoices have byte-identical historical usage snapshot hashes, line amounts, currencies, totals, stable ordering; list SQL query count exactly 2.
- Real PostgreSQL concurrency regression: twelve usage event replay calls on six threads produce one event and identical response payloads; replay with conflicting quantity/status leaves original intact.
- Existing PostgreSQL billing/payment provider, invoice finalization/idempotency and unpriced event tests.
- Full Data Platform unit/API suite, Tender Agent regression, JS SDK, Ruff, lockfile consistency, GitHub CI (Python 3.11/3.12/3.13 + pgvector).

## Remaining audit backlog

- Review billing transaction isolation under concurrent *invoice finalization*, billing assignment changes, and payment-provider idempotency. Do not alter payment reconciliation semantics without a comprehensive locked acceptance test and provider contract.
- The billable-event cursor is bounded in memory but the number of **distinct operation/unit buckets** still contributes to memory, and full invoice line sets are returned by the API by design.
- Full module inventory: `docs/audits/module_inventory.csv`. A flagged module is a review candidate; size alone is not proof of a runtime regression.
