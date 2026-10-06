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
