# Versioning policy

Arvectum Data Platform follows semantic versioning for the Python distribution and HTTP API contract.

- PATCH: compatible fixes and internal improvements.
- MINOR: backward-compatible public SDK/API additions.
- MAJOR: intentional breaking changes to public SDK/API contracts.

During the initial extraction/migration period the package remains in the 0.x series. Public import paths promoted from Discount Parser should remain stable unless a migration note and compatibility path are provided.

Every release must record the source revisions used for promoted code and must pass platform tests plus affected-consumer regression checks before duplicate product code is removed.
