from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from ..api.config import Settings
from ..api.service import DataPlatformService
from ..documents import ingest_file
from ..search import SearchMode, SearchQuery
from .corpus import CorpusArtifact, CorpusManifest, validate_corpus_manifest


FactKind = Literal["identifier", "date", "amount", "number"]


@dataclass(frozen=True, slots=True)
class FactCase:
    case_id: str
    artifact_id: str
    kind: FactKind
    fact: str
    context: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id must not be blank")
        if not self.artifact_id.strip():
            raise ValueError("artifact_id must not be blank")
        if self.kind not in {"identifier", "date", "amount", "number"}:
            raise ValueError(f"unsupported fact kind: {self.kind}")
        if not self.fact.strip():
            raise ValueError("fact must not be blank")
        if not self.context.strip():
            raise ValueError("context must not be blank")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FactCase":
        return cls(
            case_id=str(payload["id"]),
            artifact_id=str(payload["artifact_id"]),
            kind=str(payload["kind"]),  # type: ignore[arg-type]
            fact=str(payload["fact"]),
            context=str(payload["context"]),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class FactSuite:
    name: str
    corpus_manifest: Path
    cases: tuple[FactCase, ...]
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("suite name must not be blank")
        if not self.cases:
            raise ValueError("suite must contain at least one case")
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("fact case IDs must be unique")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], *, base_dir: Path) -> "FactSuite":
        raw_cases = payload.get("cases")
        if not isinstance(raw_cases, Sequence) or isinstance(raw_cases, (str, bytes)):
            raise ValueError("cases must be a list")
        metadata = dict(payload.get("metadata") or {})
        manifest_value = str(metadata.get("corpus_manifest") or "")
        if not manifest_value:
            raise ValueError("metadata.corpus_manifest is required")
        corpus_manifest = (base_dir / manifest_value).resolve()
        if not corpus_manifest.is_relative_to(base_dir.resolve()):
            raise ValueError("corpus manifest escapes benchmark directory")
        return cls(
            name=str(payload["name"]),
            description=str(payload.get("description") or ""),
            metadata=metadata,
            corpus_manifest=corpus_manifest,
            cases=tuple(FactCase.from_dict(item) for item in raw_cases),
        )


@dataclass(frozen=True, slots=True)
class FactCaseResult:
    case_id: str
    kind: FactKind
    artifact_id: str
    source_contains_fact: bool
    chunk_contains_fact: bool
    context_preserved: bool
    matching_chunk_ordinals: tuple[int, ...]
    retrieval_rank: int | None = None

    @property
    def chunk_passed(self) -> bool:
        return (
            self.source_contains_fact
            and self.chunk_contains_fact
            and self.context_preserved
        )

    @property
    def retrieval_passed(self) -> bool:
        return self.retrieval_rank == 1


@dataclass(frozen=True, slots=True)
class FactSummary:
    suite_name: str
    cases: int
    chunk_preservation_rate: float
    context_preservation_rate: float
    retrieval_top1_rate: float | None
    results: tuple[FactCaseResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_name": self.suite_name,
            "cases": self.cases,
            "chunk_preservation_rate": self.chunk_preservation_rate,
            "context_preservation_rate": self.context_preservation_rate,
            "retrieval_top1_rate": self.retrieval_top1_rate,
            "results": [
                {
                    "case_id": item.case_id,
                    "kind": item.kind,
                    "artifact_id": item.artifact_id,
                    "source_contains_fact": item.source_contains_fact,
                    "chunk_contains_fact": item.chunk_contains_fact,
                    "context_preserved": item.context_preserved,
                    "matching_chunk_ordinals": list(item.matching_chunk_ordinals),
                    "retrieval_rank": item.retrieval_rank,
                    "chunk_passed": item.chunk_passed,
                    "retrieval_passed": item.retrieval_passed,
                }
                for item in self.results
            ],
        }


def load_fact_suite(path: Path) -> FactSuite:
    suite = FactSuite.from_dict(
        json.loads(path.read_text(encoding="utf-8")),
        base_dir=path.parent,
    )
    manifest = validate_corpus_manifest(suite.corpus_manifest)
    artifact_ids = {artifact.artifact_id for artifact in manifest.artifacts}
    unknown = sorted(
        {case.artifact_id for case in suite.cases}
        - artifact_ids
    )
    if unknown:
        raise ValueError(f"fact suite references unknown corpus artifacts: {unknown}")
    return suite


def _artifact_map(manifest: CorpusManifest) -> dict[str, CorpusArtifact]:
    return {artifact.artifact_id: artifact for artifact in manifest.artifacts}


def evaluate_fact_chunking(suite: FactSuite) -> FactSummary:
    manifest = validate_corpus_manifest(suite.corpus_manifest)
    artifacts = _artifact_map(manifest)
    base_dir = suite.corpus_manifest.parent
    ingested: dict[str, Any] = {}
    results: list[FactCaseResult] = []

    for case in suite.cases:
        artifact = artifacts[case.artifact_id]
        if case.artifact_id not in ingested:
            ingested[case.artifact_id] = ingest_file(
                base_dir / artifact.file,
                collection_id=f"benchmark:{suite.name}",
                source_type="benchmark",
                canonical_uri=f"benchmark://{suite.name}/{case.artifact_id}",
            )
        result = ingested[case.artifact_id]
        source_contains = case.fact in result.document.text
        fact_chunks = tuple(
            chunk.ordinal
            for chunk in result.chunks
            if case.fact in chunk.text
        )
        context_chunks = tuple(
            chunk.ordinal
            for chunk in result.chunks
            if case.fact in chunk.text and case.context in chunk.text
        )
        results.append(
            FactCaseResult(
                case_id=case.case_id,
                kind=case.kind,
                artifact_id=case.artifact_id,
                source_contains_fact=source_contains,
                chunk_contains_fact=bool(fact_chunks),
                context_preserved=bool(context_chunks),
                matching_chunk_ordinals=context_chunks or fact_chunks,
            )
        )

    count = len(results)
    return FactSummary(
        suite_name=suite.name,
        cases=count,
        chunk_preservation_rate=(
            sum(1 for item in results if item.chunk_passed) / count
        ),
        context_preservation_rate=(
            sum(1 for item in results if item.context_preserved) / count
        ),
        retrieval_top1_rate=None,
        results=tuple(results),
    )


class PostgresFactRunner:
    def __init__(
        self,
        *,
        database_url: str,
        suite: FactSuite,
        namespace: str | None = None,
    ) -> None:
        if not database_url.strip():
            raise ValueError("database_url must not be blank")
        self.suite = suite
        self.namespace = namespace or uuid.uuid4().hex[:10]
        self.collection_id = f"benchmark:facts:{self.namespace}"
        self.service = DataPlatformService(
            Settings(
                environment="test",
                log_level="WARNING",
                database_url=database_url,
                internal_api_key="fact-benchmark-internal",
                embedding_provider="hashing",
                embedding_model="fact-preservation-v1-hash",
                embedding_dimension=32,
                embedding_retry_max_attempts=1,
                embedding_retry_base_delay_seconds=0,
                embedding_retry_max_delay_seconds=0,
            )
        )
        self.service.create_collection(
            collection_id=self.collection_id,
            owner="dp-bench-002",
            name="Fact preservation benchmark",
            default_language="simple",
        )
        self._index_artifacts()

    def _index_artifacts(self) -> None:
        manifest = validate_corpus_manifest(self.suite.corpus_manifest)
        artifacts = _artifact_map(manifest)
        base_dir = self.suite.corpus_manifest.parent
        for artifact_id in dict.fromkeys(case.artifact_id for case in self.suite.cases):
            artifact = artifacts[artifact_id]
            result = ingest_file(
                base_dir / artifact.file,
                collection_id=self.collection_id,
                source_type="benchmark",
                canonical_uri=f"benchmark://{self.suite.name}/{artifact_id}",
            )
            self.service._persist_and_index(result)

    def evaluate(self) -> FactSummary:
        chunk_summary = evaluate_fact_chunking(self.suite)
        results: list[FactCaseResult] = []

        for base in chunk_summary.results:
            case = next(item for item in self.suite.cases if item.case_id == base.case_id)
            expected_uri = f"benchmark://{self.suite.name}/{case.artifact_id}"
            hits = self.service.search(
                SearchQuery(
                    query=case.fact,
                    collections=(self.collection_id,),
                    mode=SearchMode.LEXICAL,
                    limit=5,
                )
            )
            rank = next(
                (
                    index
                    for index, hit in enumerate(hits, start=1)
                    if hit.canonical_uri == expected_uri
                ),
                None,
            )
            results.append(
                FactCaseResult(
                    case_id=base.case_id,
                    kind=base.kind,
                    artifact_id=base.artifact_id,
                    source_contains_fact=base.source_contains_fact,
                    chunk_contains_fact=base.chunk_contains_fact,
                    context_preserved=base.context_preserved,
                    matching_chunk_ordinals=base.matching_chunk_ordinals,
                    retrieval_rank=rank,
                )
            )

        count = len(results)
        return FactSummary(
            suite_name=self.suite.name,
            cases=count,
            chunk_preservation_rate=(
                sum(1 for item in results if item.chunk_passed) / count
            ),
            context_preservation_rate=(
                sum(1 for item in results if item.context_preserved) / count
            ),
            retrieval_top1_rate=(
                sum(1 for item in results if item.retrieval_passed) / count
            ),
            results=tuple(results),
        )
