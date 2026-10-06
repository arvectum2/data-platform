from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from .answers import GroundedAnswer
from .connectors import DiscoveryPage
from .models import ModelRole
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
class ResearchStageDiagnostic:
    stage: str
    status: str
    duration_ms: float
    provider: str | None = None
    model: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ResearchResult:
    query: str
    answer: GroundedAnswer
    sources: tuple[ResearchSource, ...]
    evidence: tuple[SearchHit, ...]
    warnings: tuple[str, ...]
    diagnostics: tuple[ResearchStageDiagnostic, ...] = ()


class ResearchService(Protocol):
    def discover(
        self,
        *,
        connector_name: str,
        query: str,
        cursor: str | None = None,
        limit: int = 10,
    ) -> DiscoveryPage: ...

    def ingest_url(
        self,
        *,
        collection_id: str,
        url: str,
        title: str | None = None,
    ) -> Mapping[str, Any]: ...

    def answer(
        self,
        request: SearchQuery,
        *,
        consumer: str | None = None,
    ) -> tuple[GroundedAnswer, list[SearchHit]]: ...


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
        credential_id: str | None = None,
        rerank: bool = False,
        expand_query: bool = False,
    ) -> ResearchResult:
        if not query.strip():
            raise ValueError("query must not be blank")
        if source_limit < 1 or source_limit > 25:
            raise ValueError("source_limit must be between 1 and 25")

        total_started = time.perf_counter()
        diagnostics: list[ResearchStageDiagnostic] = []

        started = time.perf_counter()
        if credential_id is None:
            page = self.service.discover(
                connector_name=connector,
                query=query,
                limit=source_limit,
            )
        else:
            page = self.service.discover(
                connector_name=connector,
                query=query,
                limit=source_limit,
                consumer=consumer,
                credential_id=credential_id,
            )
        diagnostics.append(
            ResearchStageDiagnostic(
                stage="discovery",
                status="executed",
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
                provider=connector,
                metadata={
                    "resources": len(page.resources),
                    "warnings": len(page.warnings),
                },
            )
        )

        sources: list[ResearchSource] = []
        seen: set[str] = set()
        warnings = list(page.warnings)
        attempted = ingested_count = failed_count = 0

        started = time.perf_counter()
        for resource in page.resources:
            uri = resource.canonical_uri.strip()
            if not uri or uri in seen:
                continue
            seen.add(uri)
            attempted += 1
            try:
                ingest_discovered = getattr(
                    self.service,
                    "ingest_discovered_resource",
                    None,
                )
                if credential_id is not None and callable(ingest_discovered):
                    ingest_discovered(
                        collection_id=collection_id,
                        connector_name=connector,
                        resource=resource,
                        consumer=consumer,
                        credential_id=credential_id,
                    )
                else:
                    self.service.ingest_url(
                        collection_id=collection_id,
                        url=uri,
                        title=resource.title,
                    )
                ingested_count += 1
                sources.append(
                    ResearchSource(
                        uri,
                        resource.title,
                        resource.provider,
                        resource.rank,
                        True,
                    )
                )
            except Exception as exc:
                failed_count += 1
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
                warnings.append(
                    f"source ingest failed: {uri} ({type(exc).__name__})"
                )
        diagnostics.append(
            ResearchStageDiagnostic(
                stage="acquisition-indexing",
                status="partial" if failed_count else "executed",
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
                provider="governed-url-ingest",
                metadata={
                    "attempted": attempted,
                    "ingested": ingested_count,
                    "failed": failed_count,
                },
            )
        )

        request = SearchQuery(
            query=query,
            collections=(collection_id,),
            limit=evidence_limit,
            mode=SearchMode.HYBRID,
            rerank=rerank,
            rerank_candidates=max(20, evidence_limit),
            expand_query=expand_query,
        )
        started = time.perf_counter()
        answer, hits = self.service.answer(request, consumer=consumer)
        reasoning_provider, reasoning_model = self._reasoning_identity()
        diagnostics.append(
            ResearchStageDiagnostic(
                stage="retrieval-synthesis",
                status="abstained" if answer.abstained else "executed",
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
                provider=reasoning_provider,
                model=reasoning_model,
                metadata={
                    "evidence": len(hits),
                    "claims": len(answer.claims),
                    "contradictions": len(answer.contradictions),
                },
            )
        )
        diagnostics.append(
            ResearchStageDiagnostic(
                stage="total-research",
                status="executed",
                duration_ms=round((time.perf_counter() - total_started) * 1000, 3),
                metadata={
                    "sources": len(sources),
                    "evidence": len(hits),
                },
            )
        )
        return ResearchResult(
            query=query,
            answer=answer,
            sources=tuple(sources),
            evidence=tuple(hits),
            warnings=tuple(warnings),
            diagnostics=tuple(diagnostics),
        )

    def _reasoning_identity(self) -> tuple[str | None, str | None]:
        router = getattr(self.service, "model_router", None)
        provider_method = getattr(router, "provider", None)
        if not callable(provider_method):
            return None, None
        try:
            provider = provider_method(ModelRole.REASONING)
        except Exception:
            return None, None
        descriptor = getattr(provider, "descriptor", None)
        if descriptor is None:
            return None, None
        return str(descriptor.provider), str(descriptor.model)
