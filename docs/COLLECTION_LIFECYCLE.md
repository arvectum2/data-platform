# Collection lifecycle controls

Collection lifecycle is internal-key protected and fail-safe by default.

## Retention policy

Collection creation accepts an optional retention policy with max_age_days from
1 to 36500. The policy is stored on the collection and is the authority for
manual retention pruning.

POST /v1/collections/{collection_id}/retention/prune defaults to dry_run=true.
It matches resources whose last_seen_at is older than the configured cutoff.
Only dry_run=false deletes matched resources. Resource deletion cascades through
owned documents, chunks, embeddings, records, provenance, feedback and refresh
history through the existing foreign-key model. Global canonical entities are
not deleted; source references that use SET NULL retain their shared entity.

Retention pruning is currently operator/API initiated. There is no automatic
background TTL executor yet.

## Export

GET /v1/collections/{collection_id}/export returns a bounded, paginated export
of collection-owned resources with documents, chunks, structured records and
provenance. offset defaults to 0 and limit defaults to 100, with a maximum of
1000 resources per response.

Content is opt-in. By default document text, chunk text and structured record
data are omitted while identifiers, hashes, titles, metadata and provenance
remain available. include_content=true explicitly includes those content
fields.

Embedding vectors are not exported: they are reproducible derived data and can
be regenerated from source/chunk content plus the recorded embedding contract.
Shared/global entity graph rows are not automatically exported because they can
span collections.

## Hard deletion

DELETE /v1/collections/{collection_id} is non-destructive unless confirm=true is
provided. Without confirmation it returns the owned resource/document/chunk/
embedding counts that would be removed.

With confirm=true the collection row is deleted and PostgreSQL foreign-key
rules cascade collection-owned data. Cross-collection entity references use
SET NULL rather than deleting shared canonical entities.

These controls are additive to the existing memory-specific deletion boundary.
