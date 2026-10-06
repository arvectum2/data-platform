# Connector SDK

The connector layer is the product-neutral discovery/fetch boundary of Arvectum Data Platform.

## Contract

A discovery connector implements:

~~~text
discover(query, cursor=None, limit=...) -> DiscoveryPage
health()                                -> ConnectorHealth
~~~

A fetch connector implements:

~~~text
fetch(DiscoveredResource) -> AcquisitionResult
health()                   -> ConnectorHealth
~~~

A connector may implement both capabilities.

All discovery output is normalized into `DiscoveredResource`: canonical URI, provider, source type, optional external ID/title/snippet/rank, and provider metadata.

## Built-in connectors

### manual_url

Turns one public HTTP(S) URL into a discovered resource and fetches it through the shared acquisition pipeline.

### sitemap

Uses `/sitemap.xml` first, supports sitemap indexes, and falls back to the existing bounded `URLDiscoveryCrawler` when no usable sitemap is available.

The fallback is same-origin and bounded by the Data Platform crawl policy. Its production default uses four local workers with at most two in-flight requests to the same host. Fetch completion order never changes discovery order: pages are processed in deterministic BFS queue order after each bounded batch completes.

The direct `URLDiscoveryCrawler` keeps sequential defaults for backward compatibility; consumers must opt into concurrency through `CrawlPolicy.max_workers` and `max_in_flight_per_host`. The per-host cap may never exceed the worker count.

A live `arvectum.com` acceptance on 2026-10-06 measured 25.305 s for five pages sequentially versus 15.271 s with the sitemap-fallback 4/2 policy, with identical page/link output and zero failures. This is the current scaling strategy before any distributed crawl queue.

### duckduckgo_html

Generic web discovery using the DuckDuckGo Lite HTML endpoint. The implementation contains no Tender Agent models or domain logic. It normalizes and deduplicates results before returning them as `DiscoveredResource` objects.

Search-engine HTML is an external dependency and may change; consumers should treat connector failures as provider failures, not as search-index failures.

## Registry and service API

`ConnectorRegistry` owns connector registration and capability health.

The service exposes:

~~~text
GET  /v1/connectors
POST /v1/discover
~~~

`/v1/discover` accepts a connector name, query, optional cursor and limit. Connector discovery is independent from the PostgreSQL search index, so it can be used to find sources before ingestion.

## Network safety

Default web connectors use `PublicHTTPTransport`.

It rejects:

- non-HTTP(S) URLs;
- URLs containing embedded credentials;
- localhost;
- private, link-local, multicast, reserved and otherwise non-global IP targets;
- redirects to non-public targets.

This boundary is deliberate: product-specific internal-network connectors must be explicitly separate and must not weaken the public connector defaults.

## Retry and rate limiting

`ConnectorExecutor` provides bounded exponential retry and a minimum interval between calls. Connectors may override policy values, but retries remain bounded.

The default generic web connector uses a more conservative minimum interval than manual URL discovery.

## Product boundary

44-FZ, 223-FZ and EIS remain Tender Agent connectors for now. They should implement the same Data Platform contracts when Tender Agent is migrated, but procurement law and registry semantics do not move into the Data Platform core.
