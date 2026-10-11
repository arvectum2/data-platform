# Data Platform API service boundaries

This is an internal extraction on top of Data Platform main `af5c373` (2026-10-11), not a fork of API contracts. Keep the existing [consumer boundary](TDP_CONSUMER_BOUNDARY_2026-10-09.md), SDK 0.3 / API v1, route registration and tenant isolation unchanged.

`api/service.py:DataPlatformService` composes domain mixins and remains the sole public application-service facade. API routers call this facade. The existing upstream route split (`collection_routes`, `search_routes`, `connector_routes`, `billing_routes`, `usage_routes`, `memory_routes`, `graph_routes`, etc.) is canonical; **do not recreate or register the old bundled routes**.

| Module in `src/arvectum_data/api/service_mixins` | Ownership |
|---|---|
| `access.py` | Consumer-to-tenant association and collection authorization; tenant query quotas; database/health access. The shared `_active_tenants_for_consumer` is consumed through `self` by consumer key issuance. Historical pure payload aliases remain for imports. |
| `consumer_keys.py` | API key issuance, PostgreSQL transaction advisory lock, authentication, rotation and revocation; no plaintext secret persistence. |
| `connector_credentials.py` | Encryption cipher and tenant-bound connector secret lifecycle; pure payload and metadata validation helpers reused from `api/access_payloads.py`. |
| `connector_discovery.py` | Default connector registry, discovery, credentials-aware connector selection and ingestion of discovered resources. |
| `model_readiness.py` | Model router construction and model-role readiness/metrics. |
| `billing.py` | Billing plans, pricing, invoices and payments, including tenant advisory locks and existing helper facades. |
| `usage.py` | Idempotent metering events, PostgreSQL `ON CONFLICT DO NOTHING`, and usage aggregates, preserving billing's legacy payload alias. |
| `collections.py`, `retrieval.py`, `memory_sync.py`, `graph.py`, `extraction.py` | Existing upstream collection, search, memory, graph and extraction responsibilities (unchanged in this slice). |

## Dependency / regression rules

- No sibling mixin imports or object-level instantiation: callers cross domain boundaries via `self` on `DataPlatformService` so authorization remains in place.
- Preserve the existing public method signatures, FastAPI routes, errors and SDK wire schema. Module rearrangement is **not** an API version change.
- Retain the historical `AccessServiceMixin` / `BillingServiceMixin` pure payload aliases as compatibility facades even though the owning operations moved.
- Never replace transaction/locking behavior with an earlier simpler implementation. Consumer key issuance must retain its PostgreSQL advisory lock, and metering must retain conflict-safe durable insertion.
- The existing PostgreSQL-only integration and concurrency tests, plus API/SDK contract tests, must pass in CI before any merge. Skipped local PostgreSQL tests are **not** production evidence.
- Check against the current remote `main` before integration; this branch does not change the canonical TDP `.agent/current-task.yaml` or production runtime.
