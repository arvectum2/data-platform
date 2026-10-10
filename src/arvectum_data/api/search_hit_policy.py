"""Pure, bounded deduplication policy for evidence-backed search hits.

Selection order and per-collection provenance are preserved. Keep this
independent from HTTP handlers, storage sessions and embedding providers.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..search import SearchHit


def _collapse_canonical_hits(
    hits: Sequence[SearchHit],
    *,
    limit: int,
) -> list[SearchHit]:
    seen: set[str] = set()
    results: list[SearchHit] = []
    for hit in hits:
        canonical_uri = hit.canonical_uri.strip()
        key = canonical_uri or hit.chunk_id
        if key in seen:
            continue
        seen.add(key)
        results.append(hit)
        if len(results) >= limit:
            break
    return results


def _dedupe_federated_hits(
    hits: Sequence[SearchHit],
    *,
    limit: int,
) -> list[SearchHit]:
    winners: dict[str, str] = {}
    results: list[SearchHit] = []
    for hit in hits:
        canonical_uri = hit.canonical_uri.strip()
        collection_id = str(hit.metadata.get("collection_id") or "")
        if canonical_uri and collection_id:
            winner = winners.get(canonical_uri)
            if winner is None:
                winners[canonical_uri] = collection_id
            elif winner != collection_id:
                continue
        results.append(hit)
        if len(results) >= limit:
            break
    return results
