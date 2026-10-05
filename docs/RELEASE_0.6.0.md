# Arvectum Data Platform 0.6.0

## Scope

0.6.0 introduces the first explicit multi-language consumer contract and
lightweight consumer SDKs.

## Added

- `GET /v1/contract` with semantic contract version `1.0`;
- standalone Python distribution `arvectum-data-client`;
- zero-dependency ESM package `@arvectum/data-platform-client`;
- typed/common methods for collections, document processing, ingestion,
  discovery, search and entity identity;
- consumer identity support for federated/restricted search;
- Python and JavaScript SDK conformance tests in CI.

## Boundary

The SDKs contain transport and generic contract types only. They do not contain
Tender Agent procurement semantics, Arvectum OS policy, SEO strategy or
product-specific ranking rules.

This is a backward-compatible HTTP/API addition, so the Data Platform server
moves from 0.5.0 to 0.6.0 while the consumer contract starts at 1.0.
