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

## Real multi-format corpus slice

benchmarks/corpora/public_v1/manifest.json adds the first executable source
corpus. It contains compact real public procurement and Arvectum website
artifacts in native PDF, DOCX, XLSX and HTML formats, plus two image-only PDFs
derived from real procurement pages for OCR evaluation: a linear-text baseline
and a table/form layout-stress case.

Every fixture and OCR reference text is SHA-256 pinned. The corpus runner checks
extraction status, minimum text volume and required evidence strings, reports
success by format and extraction latency, and can optionally run local
Tesseract OCR. OCR output is scored with normalized CER/WER against the pinned
reference text.

The scan reference is explicitly labelled silver rather than human-verified
gold: it comes from native extraction of the source PDF before rasterization.
A later corpus revision should add human-reviewed scan gold, malformed/legacy
documents, mixed Russian/English cases and product-research source material.

The first local Tesseract baseline on the Mac mini (rus+eng, 220 DPI) separates
two OCR profiles. The linear technical-specification scan measured CER 3.61%,
WER 5.86% and mean confidence 94.41%. The table/form layout-stress scan
measured CER 35.78%, WER 74.47% and mean confidence 86.89%. Per-artifact
regression gates are intentionally different: the linear baseline is capped at
CER 5% / WER 10%, while the layout-stress case is capped at CER 40% / WER 80%.
These are regression ceilings, not final product-quality targets.
