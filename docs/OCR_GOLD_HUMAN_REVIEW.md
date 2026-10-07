# Human review gate for OCR gold

The frozen `public_v1` OCR references remain **silver** and are not rewritten.
Their reference text was derived from native extraction before rasterization.
Human acceptance is recorded separately and promoted only through a new corpus
revision, so benchmark truth remains reproducible.

## Review request and evidence

The original immutable request is:

`benchmarks/reviews/ocr_gold_public_v1_review_request.json`

It SHA-pins the `public_v1` manifest, both image-only scan PDFs and both silver
candidate texts. The independent visual comparison is recorded separately in:

`benchmarks/reviews/ocr_gold_public_v1_ai_visual_audit_2026-10-07.json`

That audit found no substantive discrepancy in
`procurement-control-notice-scan`. For
`procurement-technical-spec-scan`, it found one reading-order/list-marker
mismatch: the silver text placed the single bullet at the document start, while
the visible scan places it before `Приложение 1. – «Перечень объектов закупки»`
under section 1.7. The proposed correction was frozen separately before human
acceptance.

## Human acceptance

Explicit human acceptance was supplied by the Product Owner in the project chat
on 2026-10-07. The accepted attestation is:

`benchmarks/reviews/ocr_gold_public_v1_accepted_2026-10-07.json`

The attestation preserves the original scan and candidate hashes, records
`reviewer_kind=human`, reviewer/date and per-item decisions, and SHA-pins both
the source review request and the supporting AI visual audit. The control notice
is `accepted_as_is`; the technical specification is
`accepted_with_corrections` and pins the separate corrected candidate.

Validation is fail-closed through:

```bash
python -m arvectum_data.evaluation.ocr_gold_review \
  benchmarks/reviews/ocr_gold_public_v1_accepted_2026-10-07.json
```

## Promotion

`public_v1` remains byte-for-byte unchanged. Human-reviewed OCR gold is promoted
in `benchmarks/corpora/public_v2/manifest.json`.

`public_v2` preserves the seven public fixtures and changes only the OCR truth
status/reference where accepted:

1. `procurement-control-notice-scan` keeps the same text and is marked
   `human-reviewed`.
2. `procurement-technical-spec-scan` uses the accepted bullet-placement
   correction and is marked `human-reviewed`.

The `public_v2` manifest records the parent manifest SHA-256 and the human
attestation SHA-256. Truth was frozen in commit
`e4202d7873ff512fc42032efa782f1bd77119f81` before the live OCR rerun.

## Acceptance result

Status: **ACCEPTED AND PROMOTED TO PUBLIC_V2**.

Live local Tesseract acceptance (`rus+eng`, 220 DPI) passed all 7/7 artifacts
against the human-reviewed revision. The layout-stress control notice measured
CER 35.78% / WER 74.47% at 86.89% confidence. The linear technical
specification measured CER 3.50% / WER 5.54% at 94.41% confidence. Both remain
inside their frozen per-artifact regression ceilings.

The recorded run is:

`benchmarks/results/data_platform_public_v2_human_gold_2026-10-07.json`
