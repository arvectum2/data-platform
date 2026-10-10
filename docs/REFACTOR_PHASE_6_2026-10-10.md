# Refactor Phase 6 — concurrency control for invoices, payment handoffs and consumer keys

**Base:** Phase 5 / PR #92, following Phase 4 / PR #91. All changes were developed in an isolated GitHub checkout on the Mac mini internal disk. No live runtime restarts, production database mutations, or schema migrations.

## Findings and fixes

| Area | Previous race | Guard and test |
|---|---|---|
| `BillingServiceMixin.finalize_invoice` | Concurrent workers could both see no invoice, calculate the same period, and try duplicate inserts; a unique constraint caused a duplicate-key error instead of returning the existing invoice | PostgreSQL transaction-scoped advisory lock keyed by tenant before the existing-invoice check and snapshot calculation. The second worker observes and returns the committed immutable invoice and lines. Eight-worker integration test verifies single invoice/single line and stable hash/total |
| `BillingServiceMixin.assign_tenant_billing` | Two simultaneous assignment updates could both see the previous active row and leave conflicting active assignments | Same tenant advisory lock surrounds read/modify/insert. Two-worker test verifies one success, one rejected duplicate-effective-date assignment, and one remaining active row |
| `BillingServiceMixin.create_invoice_payment` | Concurrent callers could each create payment handoffs before `provider_reference` was persisted | Lock invoice row with `SELECT ... FOR UPDATE` **before** the paid/reference guards and external handoff. Six-worker test confirms exactly one payment provider create call and stable payment reference |
| `BillingServiceMixin.sync_invoice_payment` and `mark_invoice_paid` | Concurrent payment reconciliation and manual marking could race, potentially overwriting terminal status with stale pending status | Same invoice row lock ensures terminal status is never downgraded. Regression test coordinates a delayed pending provider result with a manual mark-paid call |
| `AccessServiceMixin.create_consumer_key` | Two workers could both see no active keys and issue credentials for the same consumer with different tenant IDs | Transaction-scoped advisory lock keyed by consumer before querying existing tenants and issuing a new key. Two-worker integration test verifies exactly one successful tenant identity |
| `AccessServiceMixin._consumer_tenant` and issuance validation | Materialized all active key tenant IDs to detect a conflict | Reuse `SELECT DISTINCT tenant_id LIMIT 2`, excluding null/empty/expired/revoked keys. Two different tenants still fail closed; keys are not cached across requests |

## Transaction and compatibility constraints

- Advisory lock keys are namespaced: `arvectum:billing:tenant:*` and `arvectum:consumer:key:*`, hashed using PostgreSQL `hashtextextended` to a 64-bit lock key. The lock is automatically released on transaction commit or rollback; it works across multiple worker processes and host instances sharing the same PostgreSQL database.
- Both advisory and row-lock operations require PostgreSQL. This repository's production persistence is PostgreSQL/pgvector; tests run on a disposable real PostgreSQL database.
- Payment provider calls occur while the invoice row is locked. This trades short-lived lock contention for single in-flight handoff across API workers. Third-party network timeouts should remain bounded. Provider-side deterministic idempotency remains necessary if a worker crashes **after** an external payment is created but **before** the local DB commit; the existing YooKassa adapter sends a stable `Idempotence-Key` based on invoice ID.
- Invoice snapshots are unchanged. These locks guard **competing invoice finalizations and billing assignment changes**, but do **not** freeze usage-event insertion; high-scale exact cutoff semantics still warrant future billing-period freeze/ledger architecture.
- No changes to public endpoints, invoice totals, payment state payloads, consumer key hashing, SDK APIs or database schema.

## Quality gates

- Unit and full Data Platform suite.
- Real temporary PostgreSQL tests for 8-way invoice finalization, 6-way payment creation, 2-way billing assignment, consumer-key tenant ownership, revoke/replace lifecycle, and sync vs manual mark-paid race.
- Tender Agent regression across source repositories, JavaScript SDK tests, Ruff, lockfile consistency, GitHub CI Python 3.11–3.13 and pgvector integration.

## Next review targets

1. Billing-period closure/freeze semantics in the presence of usage events arriving during finalization.
2. External provider failure-after-side-effect recovery and persistent retry/orchestration, with idempotency tests across a crashed worker rather than only concurrency.
3. PostgreSQL `EXPLAIN (ANALYZE, BUFFERS)` for multi-collection search and production-scale invoice workloads, plus Mac mini memory/latency profiles.
4. Return to P1 modules `engine.html_records`, API routing and record extraction with golden parity tests before structural simplification.
