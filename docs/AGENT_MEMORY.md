# Shared evidence-backed agent memory

DP-MEM-001 uses the platform's existing collection, document, chunk, record, provenance and search layers. Memory is not a hidden global store.

## Memory classes

- `source_evidence`: a durable excerpt copied from indexed evidence. It requires source chunk IDs and the memory text must occur verbatim in at least one referenced chunk.
- `agent_observation`: an agent-derived observation. It requires source chunk IDs but may summarize or infer from them.
- `user_memory`: explicitly user-authored durable context. It does not require source evidence.

Every memory records the authenticated producer and optional declared model provider/name/version. Agent identity cannot be spoofed through the API: producer is the authenticated consumer.

## Authorization

Reading uses the normal collection `allowed_consumers` policy and normal search API. There is no global-memory fallback.

Writing is denied by default. A collection must explicitly declare `memory_writers`. User-authored memory additionally requires `user_memory_writers`. Evidence references are accepted only when the writer is authorized to read every referenced source collection.

## Provenance and conflicts

Evidence-backed memories create `dp_provenance` links to their source chunks. `subject_key` optionally identifies memories about the same fact/topic. Conflict policy is explicit:

- `append`: retain multiple active observations;
- `supersede`: mark the previous active record superseded and keep both for audit;
- `reject`: refuse a write when an active record already exists.

No model-generated observation silently overwrites another memory.

## Retention and deletion

Collection `retention_policy` remains the policy authority. Until an automated retention executor is introduced, memories are retained until explicitly deleted or their collection is deleted. `DELETE /v1/memory/{record_id}` removes the memory resource and cascades its document, chunks, embeddings, record and provenance. Deletion requires an authorized memory writer.

This is intentionally conservative: autonomous writes can be enabled now without autonomous deletion or hidden expiry.

## API

- `POST /v1/memory`
- `DELETE /v1/memory/{record_id}`
- retrieval uses existing `POST /v1/search` over explicitly authorized memory collections.
