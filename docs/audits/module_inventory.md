# Data Platform — complete module inventory and static review

The CSV beside this document contains **one individually analyzed row for every Python source module**.
Metrics are obtained by parsing the AST without importing code. Recommendations are **review candidates**, not proof of an optimization or benchmark improvement.

- Modules: **177**; total source lines: **30829**
- Priorities: P1 **11**, P2 **41**, P3 **125**
- P1: source >=600 lines, function >=200 lines or complex function >=40 decisions; P2: smaller but still large or broad-exception hotspots.
- `max_decisions` is a rough AST-based branching proxy, not a formal cyclomatic complexity measurement.

## Modules by responsibility

| Layer | Modules |
|---|---:|
| `acquisition` | 7 |
| `api` | 42 |
| `billing` | 3 |
| `connectors` | 11 |
| `core` | 2 |
| `crawl` | 5 |
| `documents` | 6 |
| `engine` | 10 |
| `evaluation` | 36 |
| `execution` | 4 |
| `indexing` | 5 |
| `models` | 4 |
| `observability` | 2 |
| `processing` | 2 |
| `results` | 6 |
| `review_queue` | 5 |
| `root` | 13 |
| `search` | 8 |
| `storage` | 6 |

## Highest-priority individual reviews

| Module | Lines | Longest function | Branches | Exception handlers |
|---|---:|---:|---:|---:|
| `api.schemas` | 881 | 20 | 5 | 0 |
| `api.service_mixins.billing` | 846 | 119 | 20 | 0 |
| `storage.postgres.repository` | 766 | 81 | 12 | 0 |
| `storage.postgres.models` | 763 | 2 | 0 | 0 |
| `results.record_sets` | 738 | 61 | 10 | 1 |
| `crawl.relevance` | 736 | 91 | 10 | 2 |
| `api.service_mixins.retrieval` | 728 | 167 | 16 | 2 |
| `api.service_mixins.access` | 720 | 46 | 11 | 1 |
| `engine.html_records` | 680 | 88 | 12 | 0 |
| `profile_lifecycle` | 668 | 69 | 10 | 3 |
| `engine.records` | 621 | 87 | 12 | 1 |

## Reproduce

`python scripts/audit_modules.py`

A P3 classification means no obvious size/branching red flag was detected; it does not mean a module has been functionally or performance-validated.
