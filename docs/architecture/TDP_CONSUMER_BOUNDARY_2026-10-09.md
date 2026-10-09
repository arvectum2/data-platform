# Data Platform consumer boundary — TDP-REFACTOR-20261009

Shared Data Platform owns generic extraction, OCR/VLM, Resource/Document/Chunk identities, chunk offsets, embeddings, search, storage, provenance and the versioned HTTP/SDK contract. Tender Agent owns EIS law/revision/registry binding, supplier/commercial rules, human decisions and tender reports. Neither repository should copy the other's implementation.

Observed: Data Platform 0.6.0, consumer contract arvectum-data-consumer 1.0, Tender Agent pins arvectum-data-client 0.3.0. The generic process/document API returns resource_id, document_id, canonical_uri, extraction_status, metadata, text, and per-chunk chunk_id, ordinal, content_hash, char_start, char_end, token_estimate.

The backward-compatible source-locator validation added here rejects empty IDs and hashes, negative positions/ordinals/estimates and spans whose char_end precedes char_start. No fake OCR pages, chunk IDs or EIS decisions may be filled to achieve apparent coverage.

Migration acceptance: retain v1 response names, check full Data Platform CI and Tender Agent consumer golden tests before changing version/release, include Russian PDF/DOCX/XLS/OCR fixtures, secure collection isolation and private original files. Health of platform or model is distinct from actual completed tender LLM workflow.

Companion roadmap: tender-agent docs/refactor/TDP_FULL_REFACTOR_MASTER_PLAN_2026-10-09.md.
