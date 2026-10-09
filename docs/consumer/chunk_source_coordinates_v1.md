# Data Platform v1 — chunk source offsets and hashes

For Arvectum consumers, API process-document chunk fields char_start and char_end are Python character offsets into the internal normalize_text(extracted_text) string. They do NOT address the raw extracted text, PDF byte stream, original Word paragraphs, OCR bounding boxes or document page numbers. A source extractor can add independent original page/paragraph/geometry locators when available, but these must be separate.

The platform normalizes CRLF, CR, nonbreaking spaces and whitespace, strips individual lines and drops blank lines before chunking. Each window can be trimmed at its boundaries when producing the returned chunk text. The chunk content_hash is the SHA256 hex digest of the actual returned chunk text encoded as UTF-8.

Consumers validating a literal claim MUST use the real returned chunk text and content_hash, verify that the quote is literally present, and label quote offsets relative to chunk text only unless they have a separately validated normalization-to-original alignment. Do not persist unredacted source text in debug logs. Do not invent page/paragraph/byte offsets based on chunk char_start/end.

This is documentation and regression coverage only. The v1 consumer JSON schema, response field names, version and SDK pin remain unchanged. R5 tender-domain source attribution and commercial/legal evidence gates belong in Tender Agent.
