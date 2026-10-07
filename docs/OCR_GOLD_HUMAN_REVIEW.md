# Human review gate for OCR gold

The public-v1 OCR references are intentionally still **silver**, not human-reviewed
gold. Their reference text was derived from native extraction before rasterization.
This document defines the remaining manual quality gate without mutating the frozen
public-v1 corpus or allowing model output to redefine truth.

## Review request

The canonical pending request is:

`benchmarks/reviews/ocr_gold_public_v1_review_request.json`

It pins the current public-v1 manifest plus both image-only scan PDFs and their
candidate reference-text files by SHA-256. Validation is fail-closed through
`arvectum_data.evaluation.ocr_gold_review`.

Current items:

1. `procurement-control-notice-scan` — layout/form stress profile.
2. `procurement-technical-spec-scan` — linear technical-specification profile.

## What the human reviewer must do

Open each pinned scan PDF and compare the visible page content to the pinned
candidate text. Check wording, numbers, punctuation where materially relevant,
table/form labels and values, and reading order. Record any correction against the
candidate text rather than judging the OCR engine's output.

The reviewer must explicitly provide a human identity/name or stable review label,
review date, per-item accepted/pending status, and notes for any discrepancy.
Automated model output, OCR output, native parser output or benchmark results do not
count as human review.

## Acceptance and promotion

Do **not** edit the pending request in place. After a human completes the review,
create a separate accepted attestation file that preserves the same source hashes
and sets every item to `review.status=accepted`,
`reviewer_kind=human`, reviewer and reviewed_at.

Then validate it with:

```bash
python -m arvectum_data.evaluation.ocr_gold_review \
  benchmarks/reviews/<accepted-attestation>.json
```

Human acceptance still does not permit editing `public_v1`. Promotion must create
a new corpus/benchmark revision (for example public_v2) whose gold files are the
human-reviewed texts and whose manifest records the review attestation/hash. The
existing v1 silver corpus remains immutable for reproducibility.

## Current gate

Status: **PENDING HUMAN REVIEW**.

Engineering preparation is complete when the pending packet validates and CI is
green. The quality claim "human-reviewed OCR gold" remains blocked until an actual
human performs and records the comparison.
