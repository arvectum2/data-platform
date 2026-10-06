from __future__ import annotations

from arvectum_data.answers import GroundedAnswer
from arvectum_data.connectors import DiscoveredResource, DiscoveryPage
from arvectum_data.research import ResearchWorkflow


class FakeService:
    def __init__(self):
        self.ingested = []
        self.answer_request = None

    def discover(self, **kwargs):
        return DiscoveryPage(
            resources=(
                DiscoveredResource("https://a.example/x", "test", title="A", rank=1),
                DiscoveredResource("https://a.example/x", "test", title="duplicate", rank=2),
                DiscoveredResource("https://b.example/y", "test", title="B", rank=3),
            ),
            warnings=("discovery warning",),
        )

    def ingest_url(self, *, collection_id, url, title=None):
        self.ingested.append(url)
        if "b.example" in url:
            raise RuntimeError("blocked")
        return {"resource_id": "r"}

    def answer(self, request, *, consumer=None):
        self.answer_request = request
        return (
            GroundedAnswer(
                answer=None,
                claims=(),
                contradictions=(),
                uncertainty="reasoning disabled",
                abstained=True,
            ),
            [],
        )


def test_research_deduplicates_and_isolates_source_failures():
    service = FakeService()
    result = ResearchWorkflow(service).run(
        query="research question",
        collection_id="research:test",
        source_limit=5,
        evidence_limit=4,
    )
    assert service.ingested == ["https://a.example/x", "https://b.example/y"]
    assert len(result.sources) == 2
    assert result.sources[0].ingested is True
    assert result.sources[1].ingested is False
    assert result.sources[1].error == "RuntimeError"
    assert "discovery warning" in result.warnings
    assert any("source ingest failed" in warning for warning in result.warnings)
    assert service.answer_request.collections == ("research:test",)
    assert service.answer_request.limit == 4
    assert result.answer.abstained is True
    by_stage = {item.stage: item for item in result.diagnostics}
    assert set(by_stage) == {
        "discovery",
        "acquisition-indexing",
        "retrieval-synthesis",
        "total-research",
    }
    assert by_stage["discovery"].provider == "duckduckgo_html"
    assert by_stage["acquisition-indexing"].status == "partial"
    assert by_stage["acquisition-indexing"].metadata == {
        "attempted": 2,
        "ingested": 1,
        "failed": 1,
    }
    assert by_stage["retrieval-synthesis"].status == "abstained"
    assert all(item.duration_ms >= 0 for item in result.diagnostics)
    assert "research question" not in repr(result.diagnostics)


def test_research_bounds_source_expansion():
    service = FakeService()
    workflow = ResearchWorkflow(service)
    try:
        workflow.run(query="q", collection_id="c", source_limit=26)
    except ValueError as exc:
        assert "source_limit" in str(exc)
    else:
        raise AssertionError("expected source limit validation")
