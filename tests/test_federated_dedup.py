from arvectum_data.api.service import DataPlatformService
from arvectum_data.search import SearchEvidence, SearchHit, SearchScores


def _hit(
    chunk_id: str,
    canonical_uri: str,
    collection_id: str,
    fusion: float,
) -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        resource_id=f"res-{chunk_id}",
        canonical_uri=canonical_uri,
        title=chunk_id,
        preview=chunk_id,
        text=chunk_id,
        scores=SearchScores(lexical=None, vector=0.9, fusion=fusion),
        evidence=(
            SearchEvidence(
                resource_id=f"res-{chunk_id}",
                document_id=f"doc-{chunk_id}",
                chunk_id=chunk_id,
                canonical_uri=canonical_uri,
            ),
        ),
        metadata={"collection_id": collection_id},
    )


def test_federated_dedup_suppresses_only_cross_collection_uri_duplicates() -> None:
    hits = [
        _hit("site-1", "https://example.com/product", "site", 0.040),
        _hit("product-1", "https://example.com/product", "products", 0.039),
        _hit("site-2", "https://example.com/product", "site", 0.038),
        _hit("other-1", "https://example.com/other", "products", 0.037),
    ]

    deduped = DataPlatformService._dedupe_federated_hits(hits, limit=3)

    assert [hit.chunk_id for hit in deduped] == [
        "site-1",
        "site-2",
        "other-1",
    ]


def test_page_level_collapse_suppresses_all_canonical_uri_duplicates() -> None:
    hits = [
        _hit("site-1", "https://example.com/product", "site", 0.040),
        _hit("site-2", "https://example.com/product", "site", 0.039),
        _hit("product-1", "https://example.com/product", "products", 0.038),
        _hit("other-1", "https://example.com/other", "products", 0.037),
    ]

    collapsed = DataPlatformService._collapse_canonical_hits(hits, limit=3)

    assert [hit.chunk_id for hit in collapsed] == ["site-1", "other-1"]
