# Competitive benchmark foundation

DP-BENCH-002 is benchmark-driven: retrieval, OCR, reranking, VLM escalation,
query expansion and answer synthesis are not promoted merely because an
implementation exists.

## Frozen catalog

The file benchmarks/catalog_v1.json is the versioned registry of executable
benchmark suites. Each entry records:

- a stable suite ID and relative file path;
- SHA-256 of the frozen JSON suite;
- expected case count;
- visibility: public or private-derived;
- covered benchmark dimensions;
- minimum acceptance thresholds.

The catalog validator fails closed when a suite is changed without updating its
digest or declared case count. This makes benchmark revisions explicit in code
review instead of silently moving the target.

Raw production documents are not committed by this catalog. Production-derived
suites contain accepted queries and evidence identities only and are labelled
private-derived. Public/shareable suites remain distinguishable at the catalog
layer.

## Metric primitives

The evaluation package now provides reusable metric primitives for later
competitive runners:

- character error rate (CER) and word error rate (WER) for OCR;
- nDCG@k for graded retrieval relevance;
- set precision/recall for citation completeness/correctness and similar
  evidence-set checks.

The existing retrieval evaluator continues to report top-1, MRR, hit rate,
recall and latency. The next DP-BENCH-002 increments should add frozen
multi-format source fixtures, OCR/layout gold data, adversarial isolation and
conflict cases, and reference-product adapters. Those dimensions remain open
until measured rather than being checked off from implementation alone.
