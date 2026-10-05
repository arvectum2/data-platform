# Data Platform consumer contract and SDKs

## Purpose

All Arvectum products consume the same product-neutral Data Platform over the
versioned HTTP contract. Domain code stays in the consumer; acquisition,
document processing, indexing, retrieval, entity identity and provenance stay
in Data Platform.

The canonical direction is:

```text
Tender Agent / Arvectum OS / Growth & SEO / future agents
                         |
                         v
              Data Platform HTTP API
                         |
               generic data/search core
```

Data Platform never imports consumer code.

## Contract discovery

Consumers can call `GET /v1/contract`. The response publishes:

- contract name and semantic version;
- API prefix;
- supported generic capabilities;
- canonical authentication header names.

Consumer contract `1.x` is backward-compatible. A future incompatible HTTP
contract increments the major version. SDKs expose an explicit compatibility
check and do not silently fall back to local implementations.

## Python SDK

The lightweight distribution lives under `sdk/python` and is named
`arvectum-data-client`. It depends only on `httpx`; consumers do not need to
install the Data Platform server, PostgreSQL, extractors or embedding stack.

Primary import:

```python
from arvectum_data_client import DataPlatformClient

with DataPlatformClient(
    base_url="http://127.0.0.1:8094",
    api_key="...",
) as client:
    client.require_contract(1)
    hits = client.search(
        query="кабель силовой",
        collections=["growth:products"],
        limit=10,
    )
```

The SDK intentionally returns ordinary typed dictionaries so existing Arvectum
consumers can migrate without translating their domain code to SDK-specific
runtime models.

## JavaScript SDK

The zero-dependency ESM client lives under `sdk/javascript`. The repository
root `package.json` exposes it as `@arvectum/data-platform-client`.

```javascript
import { DataPlatformClient } from "@arvectum/data-platform-client";

const client = new DataPlatformClient({
  baseUrl: process.env.DATA_PLATFORM_URL || "http://127.0.0.1:8094",
  apiKey: process.env.DATA_PLATFORM_API_KEY || "",
});

await client.requireContract(1);
const result = await client.search({
  query: "AI procurement automation",
  collections: ["growth:arvectum-site"],
});
```

## Supported v1 consumer surface

The SDKs cover the shared cross-product surface with parity between Python and JavaScript:

- collection creation/existence/stats;
- document processing without persistence;
- document ingestion;
- URL ingestion;
- lexical/vector/hybrid search;
- connector discovery;
- entity resolution/creation;
- entity relations;
- health and contract compatibility.

Consumer-specific ranking presets, tender evidence mapping, SEO intent strategy,
report generation and agent policy remain outside the SDK.

## Authentication

`X-Arvectum-Key` authenticates the internal service API when configured.

Federated or restricted multi-collection search additionally uses:

- `X-Arvectum-Consumer`;
- `X-Arvectum-Consumer-Key`.

Both SDKs accept consumer identity at client construction and attach it only
where the HTTP contract requires it.

## Release discipline

The server package, Python SDK and JavaScript SDK have independent package
versions. The HTTP consumer contract has its own semantic version.

A release that changes the consumer surface must pass:

1. Data Platform unit/API tests;
2. Python SDK conformance tests;
3. JavaScript SDK conformance tests;
4. affected consumer regression tests before duplicated client code is removed.
