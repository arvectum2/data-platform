# Migration source ledger

## DP-MIG-001 — Discount Parser generic engine

- source repository: arvectum2/discount-parser
- source revision: 4bde0909d18b
- source path: arvectum_data/
- destination package: src/arvectum_data/
- initial promoted focused tests: 18 product-independent tests from tests/dp_engine/

Product-coupled acceptance/parity tests intentionally remain in Discount Parser:

- test_engine_acceptance.py
- test_engine_acceptance_cli.py
- test_live_semantic_remediation.py
- test_production_source_runtime.py
- test_source_parity_telemetry.py

Those tests depend on Discount Parser source adapters, configuration, parity telemetry or CLI and therefore validate the consumer integration rather than the neutral platform package.
