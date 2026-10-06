# Public crawl transport benchmark

Date: 2026-10-06

The single-node crawler appeared to be a distributed-crawling bottleneck only because the public HTTP transport spent almost the entire socket timeout on an unreachable IPv6 address before reaching a healthy IPv4 address.

## Diagnosis

On the production Mac mini, `arvectum.com` resolved to both IPv6 and IPv4. IPv4 completed in about 76 ms while direct IPv6 timed out after about 10 seconds. `validate_public_url` itself took only about 0.5–2.7 ms, proving the SSRF/DNS validation path was not the bottleneck.

Before the fix, three `PublicHTTPTransport.fetch()` runs took approximately 8261, 8068 and 8062 ms. After connecting to the already-validated address set with IPv4 preference and bounded address-family failover, the same runs took approximately 64, 57 and 81 ms — about 121x faster on the mean.

## Crawl acceptance

With the repaired transport and the existing sequential bounded `URLDiscoveryCrawler`:

- 10-page bounded run: 0.631 s, 15.84 pages/s, 0 failures;
- full reachable site graph under a 50-page ceiling: 41 pages in 3.186 s, 12.87 pages/s, 0 failures;
- no renderer was used; same-origin policy and normal SSRF checks remained enabled.

The frozen measurements are in `benchmarks/results/crawl_transport_2026-10-06.json`.

## Security properties

The repaired transport:

- resolves and validates every target before connecting;
- rejects the request if any resolved address is non-public;
- pins the connection to one of the validated public addresses, reducing DNS-rebinding exposure;
- prefers IPv4 on dual-stack hosts but retains IPv6 fallback;
- verifies the original hostname during TLS;
- re-resolves and re-validates every redirect target before following it;
- rejects Authorization, Proxy-Authorization, Cookie and Host headers on the generic public transport;
- preserves response-size and redirect-count bounds.

Credential-aware connectors such as private GitHub use their own connector-specific transport and are not routed through the generic public transport.

## Distributed crawling decision

DP-CRAWL-002 remains deferred. The measured single-node public crawl path now sustains roughly 13–16 pages/s on the acceptance site, and the tested site graph completes in a few seconds. There is no measured throughput justification yet for durable crawl queues, leases and multiple workers.

Distributed crawling should only be reconsidered when a representative production corpus demonstrates a repeatable throughput or recovery bottleneck that cannot be solved by bounded single-node execution.
