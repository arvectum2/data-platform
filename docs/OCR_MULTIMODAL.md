# OCR and multimodal ingestion

DP-OCR-001 uses an escalation cascade rather than treating every PDF as a vision task.

1. Native deterministic extraction is attempted per PDF page.
2. Pages with fewer than the configured native-text threshold are sent to a local OCR provider.
3. Only OCR pages with too little text or low confidence are eligible for VLM escalation.
4. A VLM is used only when the vision role is explicitly configured through DP-MODEL-001.

## Local OCR

The first implementation is `TesseractOCRProvider`. It renders only selected PDF pages through a fixed `pdftoppm` binary and runs a fixed local Tesseract binary. The provider returns page identity, aggregate confidence and word-level bounding boxes.

Runtime configuration:

- `ARVECTUM_DATA_OCR_PROVIDER=disabled|tesseract`
- `ARVECTUM_DATA_OCR_LANGUAGES=rus+eng`
- `ARVECTUM_DATA_OCR_DPI=220`
- `ARVECTUM_DATA_OCR_TIMEOUT_SECONDS=45`

OCR is disabled by default so deployments without the local binaries preserve the existing deterministic ingestion behavior.

## VLM escalation and remote safety

VLM escalation reuses the vision provider boundary from DP-MODEL-001. Therefore a remote VLM cannot be reached unless the vision role is configured as `remote-allowlist` and its endpoint hostname is explicitly allowlisted. There is no OCR-to-cloud fallback.

The VLM prompt asks for faithful extraction and preservation of tables/forms as Markdown tables or labeled fields. The resulting document keeps page markers, while metadata records the escalation reason, provider/model and locality.

## Provenance

PDF metadata records:

- page number and native character count;
- whether the page required OCR;
- OCR provider, page list and mean confidence;
- word-level OCR text/confidence/bounding boxes;
- VLM page, escalation reason, provider/model and locality.

## Real procurement acceptance

On 2026-10-05 the local cascade was run against a real scanned procurement PDF from the existing Tender Agent corpus. Native PDF extraction returned zero characters. Tesseract OCR selected only the scan page and returned 925 characters with mean confidence 93.16%, including the document heading and NMCK text. No VLM was needed for this document.

## Benchmark-driven VLM routing threshold

The first two frozen scan profiles exposed a weakness in the original
confidence-only threshold of 70. The layout-stress procurement form measured
86.89% mean Tesseract confidence but still had CER 35.78% / WER 74.47%, while
the linear technical-specification scan measured 94.41% confidence with CER
3.61% / WER 5.86%.

The default VLM escalation confidence threshold is therefore 90. With a vision
provider configured, the layout-stress profile is routed to VLM escalation and
the linear baseline remains on OCR. Vision is still never invoked when the
vision role is disabled, so this does not introduce an implicit cloud path.
The frozen vlm_routing_v1 gate requires 100% routing accuracy on these accepted
profiles.

## Private runtime scale benchmark

A SHA-only private-derived suite now freezes nine real first-page PDF cases
without storing source paths, filenames, native text or OCR text in Git:

- 8 procurement documents from the Tender Agent runtime;
- 1 business review document;
- native PDF text acts as independent page-level gold;
- local Tesseract runs at rus+eng / 220 DPI.

The 2026-10-06 reproducible run measured median CER 9.81%, median WER 11.03%,
mean confidence 91.86%, p50 latency about 1.39 s and p95 about 2.46 s.

For routing evaluation, OCR is classified as poor when CER > 25% or WER > 50%.
Three of nine cases crossed that quality boundary. All three had Tesseract
confidence below the current 90 escalation threshold (89.14, 87.53 and 86.29),
while all six acceptable cases stayed at or above 90. The current threshold
therefore achieved routing precision=1.0, recall=1.0 and accuracy=1.0 on this
larger real private-derived sample.

The frozen suite is benchmarks/private_runtime_ocr_scale_v1.json and the
privacy-safe run output is
benchmarks/results/private_runtime_ocr_scale_2026-10-06.json.

## Live local VLM quality benchmark

A separate local benchmark environment now provides the missing content-quality
comparison without enabling vision in production. Using mlx-vlm 0.7.6 with
mlx-community/Qwen2.5-VL-3B-Instruct-4bit on the two frozen public scan
profiles, required-text recall was 100%. Mean CER improved from 19.70% with
Tesseract to 13.95% with the VLM, and mean WER improved from 40.17% to 23.50%.

The gain is concentrated exactly where the routing gate predicts it should be.
The layout-stress form improved from CER 35.78% / WER 74.47% to CER 25.48% /
WER 41.13%. The linear technical-specification scan improved only from CER
3.61% / WER 5.86% to CER 2.42% / WER 5.86%.

The cost difference is large: cached model load was about 4.84 s, warm-up about
7.27 s, page inference about 13.19-16.95 s, and MLX reported about 4.13 GB peak
memory. Tesseract took about 1.25 s on the layout-stress page and 2.77 s on the
linear page. Therefore the benchmark confirms the current design: keep
Tesseract as the ordinary OCR path and invoke a local VLM only for pages that
fail the OCR-quality/routing threshold. Production vision remains disabled
unless explicitly configured through DP-MODEL-001.

Reproduce the local VLM comparison with
`scripts/benchmark_mlx_vlm_reference.py`; the frozen outputs are
`benchmarks/results/mlx_vlm_public_scans_2026-10-06.json` and
`benchmarks/results/mlx_vlm_vs_tesseract_2026-10-06.json`.
