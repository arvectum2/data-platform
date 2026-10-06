# Tenancy and quotas

Data Platform separates authentication identity from tenant identity.

A consumer is an authenticated application or agent identified by
X-Arvectum-Consumer and X-Arvectum-Consumer-Key. A tenant is the owning
customer/security boundary. Multiple consumers may map to one tenant.

## Configuration

consumer_api_keys authenticates consumers.

consumer_tenants maps authenticated consumer IDs to tenant IDs. The mapping is
optional for backward compatibility with existing first-party consumers.

tenant_quotas maps tenant IDs to bounded search quotas. Supported keys are:

- max_collections_per_search;
- max_results_per_search;
- max_rerank_candidates;
- max_query_variants.

Quota violations fail closed with HTTP 429. Platform-wide hard ceilings still
apply first and cannot be raised by a tenant quota.

## Collection policy

Collection access_policy accepts:

- tenant_id: optional tenant security boundary;
- allowed_consumers: optional additional consumer-level narrowing.

When tenant_id is present, an authenticated consumer must map to that same
tenant. If allowed_consumers is also non-empty, the consumer must pass both
checks. This permits multiple agents for one customer without making consumer
identity itself the tenant boundary.

Collections without tenant_id preserve the existing 1.x compatibility model.

## Enforcement

Tenant authorization is implemented inside DataPlatformService, not only in the
HTTP layer. Direct Python callers therefore cannot bypass the collection
boundary. Search, source-evidence memory writes and memory deletion use the same
centralized collection authorization helper.

Search quotas are also checked in the service before retrieval, so the HTTP
route and direct service callers share the same limits.

Federated search remains fail-closed: every requested collection must authorize
the tenant/consumer. Unauthorized collections are never silently omitted.

## Acceptance

The frozen adversarial PostgreSQL suite uses two distinct tenant mappings. The
tenant-isolation case verifies that a tenant-A consumer is denied access to a
tenant-B collection while a tenant-B consumer can retrieve the expected
evidence. The full adversarial suite remains 5/5 after tenant-boundary
enforcement.

These quotas are resource/request quotas, not billing metering or rate-limit
accounting. Billing and customer-facing key lifecycle remain separate product
work.
