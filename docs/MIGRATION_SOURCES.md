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


### Consumer cutover

- Data Platform canonical commit: a591256f50a21b8618639129eccb15eb214204d5
- Discount Parser cutover commit: e0e303999e8fb1c2d6665f9013d3ad0d7ea1c2d7
- dependency form: pinned public Git VCS dependency
- focused consumer verification: 289 tests passed
- full Discount Parser regression: 634 tests passed
- vendored arvectum_data package removed from Discount Parser after acceptance
