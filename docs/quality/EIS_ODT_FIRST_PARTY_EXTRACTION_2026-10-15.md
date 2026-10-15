# Data Platform — original EIS ODT text extraction, 15 Oct 2026

Technical DEVELOPMENT acceptance only. A saved 44-FZ procurement ZIP may
reference OpenDocument Text (*.odt), including a required NMCK price justification.

Previously, Data Platform recognized the attachment but returned
`extraction_status=unsupported`, making Tender Agent extract 16/17
documents from the official archived development case 0162200011826003089.

This change adds an in-process, bounded ODF extractor to the **Data Platform**
document boundary. It validates the canonical `mimetype` ZIP member,
accepts exactly one `content.xml`, bounds its decompressed size (8 MiB),
compressed ratio, archive member count, rejects DTD/entities, and projects
text headings, paragraphs, whitespace and table rows. It does not execute
external converters, macros, OCR, embedded links or network calls. File
extension cannot override a valid, different OOXML/OFD signature.

Verified against the already saved first-party original, without committing
its bytes: `3. Обоснование НМЦК.odt` from archived 44-FZ
№0162200011826003089 — **3,447 extracted characters, 24 lines**.
A local Data Platform HTTP process produced **3 chunks** from the same
preserved original. No procurement or source original was altered.

Targeted tests cover real ODF text/tables, mislabeled extension, fake ZIP,
wrong mimetype, malformed XML, DTD entity injection, decompression size
budget, duplicate members, and max text truncation. All existing
`tests/documents/` regression passes. No source plaintext in GitHub.

This does **not** attest completeness of all source-table semantics,
current EIS revision or commercial eligibility. Upstream Tender Agent full
17-document Gemma E2E is recorded in its separate checkpoint.
