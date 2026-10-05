from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .answers import GroundedAnswer
from .connectors import DiscoveryPage
from .search import SearchHit, SearchMode, SearchQuery


@dataclass(frozen=True, slots=True)
class ResearchSource:
    canonical_uri: str
    title: str | None
    provider: str
    rank: int | None
    ingested: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ResearchResult:
    query: str
    answer: GroundedAnswer
    sources: tuple[ResearchSource, ...]
    evidence: tuple[SearchHit, ...]
    warnings: tuple[str, ...]


class ResearchService(Protocol):
    def discover(self, *, connector_name: str, query: str, cursor: str | None = None, limit: int = 10) -> DiscoveryPage: ...
    def ingest_url(self, *, collection_id: str, url: str, title: str | None = None) -> Mapping[str, Any]: ...
    def answer(self, request: SearchQuery, *, consumer: str | None = None) -> tuple[GroundedAnswer, list[SearchHit]]: ...


class ResearchWorkflow:
    """Bounded discovery -> governed ingest -> retrieval -> grounded synthesis."""

    def __init__(self, service: ResearchService) -> None:
        self.service = service

    def run(
        self,
        *,
        query: str,
        collection_id: str,
        connector: str = "duckduckgo_html",
        source_limit: int = 8,
        evidence_limit: int = 8,
        consumer: str | None = None,
        rerank: bool = False,
        expand_query: bool = False,
    ) -> ResearchResult:
        if not query.strip():
            raise ValueError("query must not be blank")
        if source_limit < 1 or source_limit > 25:
            raise ValueError("source_limit must be between 1 and 25")
        page = self.service.discover(
            connector_name=connector,
            query=query,
            limit=source_limit,
        )
        sources: list[ResearchSource] = []
        seen: set[str] = set()
        warnings = list(page.warnings)
        for resource in page.resources:
            uri = resource.canonical_uri.strip()
            if not uri or uri in seen:
                continue
            seen.add(uri)
            try:
                self.service.ingest_url(
                    collection_id=collection_id,
                    url=uri,
                    title=resource.title,
                )
                sources.append(
                    ResearchSource(uri, resource.title, resource.provider, resource.rank, True)
                )
            except Exception as exc:
                sources.append(
                    ResearchSource(
                        uri,
                        resource.title,
                        resource.provider,
                        resource.rank,
                        False,
                        type(exc).__name__,
                    )
                )
                warnings.append(f"source ingest failed: {uri} ({type(exc).__name__})")

        request = SearchQuery(
            query=query,
            collections=(collection_id,),
            limit=evidence_limit,
            mode=SearchMode.HYBRID,
            rerank=rerank,
            rerank_candidates=max(20, evidence_limit),
            expand_query=expand_query,
        )
        answer, hits = self.service.answer(request, consumer=consumer)
        return ResearchResult(
            query=query,
            answer=answer,
            sources=tuple(sources),
            evidence=tuple(hits),
            warnings=tuple(warnings),
        )
