# Arvectum Data Platform Consumer SDK 0.2.0

## Scope

0.2.0 closes the remaining Python/JavaScript parity gaps without changing the
HTTP consumer contract major (1.x).

## Added

- JavaScript collectionExists(collectionId);
- JavaScript processDocument(...) for non-persistent extraction/chunking;
- conformance coverage proving both operations use the canonical HTTP contract.

## Compatibility

This is additive and backward-compatible. Existing 0.1.x consumers keep
working against consumer contract 1.x.
