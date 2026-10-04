from arvectum_data.acquisition import AcquisitionEngine, PageSnapshot
from arvectum_data.documents import ingest_url
from arvectum_data.processing import ChunkingConfig


class StaticTransport:
    name = "static"

    def fetch(self, request):
        return PageSnapshot(
            requested_url=request.url,
            final_url="https://example.com/final",
            status_code=200,
            content_type="text/html; charset=utf-8",
            body=(
                "<html><body><h1>Каталог</h1><p>"
                + ("Силовой кабель для промышленного объекта. " * 30)
                + "</p></body></html>"
            ).encode("utf-8"),
        )


def test_ingest_url_builds_scoped_document_and_chunks() -> None:
    engine = AcquisitionEngine(http=StaticTransport(), renderer=None)
    result = ingest_url(
        "https://example.com/start",
        collection_id="growth:web",
        acquisition=engine,
        chunking=ChunkingConfig(
            chunk_size_chars=180,
            overlap_chars=30,
            min_chunk_chars=50,
        ),
    )

    assert result.resource.collection_id == "growth:web"
    assert result.resource.source_type == "url"
    assert result.resource.canonical_uri == "https://example.com/final"
    assert result.document.media_type == "text/html"
    assert "<html>" not in result.document.text
    assert result.chunks
    assert all(chunk.provenance.canonical_uri == "https://example.com/final" for chunk in result.chunks)


def test_url_ingest_is_idempotent_for_same_content() -> None:
    engine = AcquisitionEngine(http=StaticTransport(), renderer=None)
    first = ingest_url(
        "https://example.com/start",
        collection_id="growth:web",
        acquisition=engine,
    )
    second = ingest_url(
        "https://example.com/start",
        collection_id="growth:web",
        acquisition=engine,
    )

    assert first.resource.resource_id == second.resource.resource_id
    assert first.document.document_id == second.document.document_id
