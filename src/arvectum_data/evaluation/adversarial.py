from __future__ import annotations

import json
import tempfile
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from unittest.mock import patch

from ..api.config import Settings
from ..api.service import CollectionAccessDenied, DataPlatformService
from ..documents import ingest_file
from ..search import SearchMode, SearchQuery
from ..storage.postgres import ResourceRow


AdversarialKind = Literal[
    "collection_isolation",
    "tenant_isolation",
    "duplicate_content",
    "conflicting_evidence",
    "stale_source",
]


@dataclass(frozen=True, slots=True)
class AdversarialCase:
    case_id: str
    kind: AdversarialKind
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id must not be blank")
        if self.kind not in {
            "collection_isolation",
            "tenant_isolation",
            "duplicate_content",
            "conflicting_evidence",
            "stale_source",
        }:
            raise ValueError(f"unsupported adversarial kind: {self.kind}")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AdversarialCase":
        return cls(
            case_id=str(payload["id"]),
            kind=str(payload["kind"]),  # type: ignore[arg-type]
            description=str(payload.get("description") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class AdversarialSuite:
    name: str
    cases: tuple[AdversarialCase, ...]
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("suite name must not be blank")
        if not self.cases:
            raise ValueError("suite must contain at least one case")
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("adversarial case IDs must be unique")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AdversarialSuite":
        raw_cases = payload.get("cases")
        if not isinstance(raw_cases, Sequence) or isinstance(raw_cases, (str, bytes)):
            raise ValueError("cases must be a list")
        return cls(
            name=str(payload["name"]),
            description=str(payload.get("description") or ""),
            metadata=dict(payload.get("metadata") or {}),
            cases=tuple(AdversarialCase.from_dict(item) for item in raw_cases),
        )


@dataclass(frozen=True, slots=True)
class AdversarialObservation:
    case_id: str
    kind: AdversarialKind
    passed: bool
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AdversarialSummary:
    suite_name: str
    cases: int
    passed: int
    pass_rate: float
    observations: tuple[AdversarialObservation, ...]

    @property
    def all_passed(self) -> bool:
        return self.passed == self.cases

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_name": self.suite_name,
            "cases": self.cases,
            "passed": self.passed,
            "pass_rate": self.pass_rate,
            "all_passed": self.all_passed,
            "observations": [
                {
                    "case_id": item.case_id,
                    "kind": item.kind,
                    "passed": item.passed,
                    "details": dict(item.details),
                }
                for item in self.observations
            ],
        }


AdversarialRunner = Callable[[AdversarialCase], AdversarialObservation]


def load_adversarial_suite(path: Path) -> AdversarialSuite:
    return AdversarialSuite.from_dict(json.loads(path.read_text(encoding="utf-8")))


def evaluate_adversarial_suite(
    suite: AdversarialSuite,
    runner: AdversarialRunner,
) -> AdversarialSummary:
    observations: list[AdversarialObservation] = []
    for case in suite.cases:
        try:
            observation = runner(case)
            if observation.case_id != case.case_id or observation.kind != case.kind:
                raise ValueError("runner returned observation for the wrong case")
        except Exception as exc:
            observation = AdversarialObservation(
                case_id=case.case_id,
                kind=case.kind,
                passed=False,
                details={"error_type": type(exc).__name__},
            )
        observations.append(observation)
    passed = sum(1 for item in observations if item.passed)
    return AdversarialSummary(
        suite_name=suite.name,
        cases=len(observations),
        passed=passed,
        pass_rate=passed / len(observations),
        observations=tuple(observations),
    )


class PostgresAdversarialRunner:
    def __init__(
        self,
        *,
        database_url: str,
        namespace: str | None = None,
    ) -> None:
        if not database_url.strip():
            raise ValueError("database_url must not be blank")
        self.namespace = namespace or uuid.uuid4().hex[:10]
        self.service = DataPlatformService(
            Settings(
                environment="test",
                log_level="WARNING",
                database_url=database_url,
                internal_api_key="adversarial-internal",
                consumer_api_keys={
                    "tenant-a": "tenant-a-key",
                    "tenant-b": "tenant-b-key",
                },
                embedding_provider="hashing",
                embedding_model="adversarial-v1-hash",
                embedding_dimension=32,
                embedding_retry_max_attempts=1,
                embedding_retry_base_delay_seconds=0,
                embedding_retry_max_delay_seconds=0,
                allow_private_fetches=True,
            )
        )

    def __call__(self, case: AdversarialCase) -> AdversarialObservation:
        handlers: dict[AdversarialKind, Callable[[AdversarialCase], AdversarialObservation]] = {
            "collection_isolation": self._collection_isolation,
            "tenant_isolation": self._tenant_isolation,
            "duplicate_content": self._duplicate_content,
            "conflicting_evidence": self._conflicting_evidence,
            "stale_source": self._stale_source,
        }
        return handlers[case.kind](case)

    def _collection_id(self, suffix: str) -> str:
        return f"benchmark:adv:{self.namespace}:{suffix}"

    def _create_collection(
        self,
        suffix: str,
        *,
        allowed_consumers: tuple[str, ...] = (),
    ) -> str:
        collection_id = self._collection_id(suffix)
        policy = (
            {"allowed_consumers": list(allowed_consumers)}
            if allowed_consumers
            else None
        )
        self.service.create_collection(
            collection_id=collection_id,
            owner="dp-bench-002",
            name=f"Adversarial {suffix}",
            default_language="simple",
            access_policy=policy,
        )
        return collection_id

    def _ingest_text(
        self,
        *,
        collection_id: str,
        canonical_uri: str,
        text: str,
        source_type: str = "file",
    ):
        with tempfile.NamedTemporaryFile(suffix=".txt") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            result = ingest_file(
                handle.name,
                collection_id=collection_id,
                source_type=source_type,
                canonical_uri=canonical_uri,
                title=canonical_uri.rsplit("/", 1)[-1],
                pre_chunked=True,
            )
        self.service._persist_and_index(result)
        return result

    def _search(
        self,
        query: str,
        collections: tuple[str, ...],
        *,
        consumer: str | None = None,
        limit: int = 10,
    ):
        return self.service.search(
            SearchQuery(
                query=query,
                collections=collections,
                mode=SearchMode.LEXICAL,
                limit=limit,
            ),
            consumer=consumer,
        )

    def _observation(
        self,
        case: AdversarialCase,
        passed: bool,
        **details: Any,
    ) -> AdversarialObservation:
        return AdversarialObservation(
            case_id=case.case_id,
            kind=case.kind,
            passed=passed,
            details=details,
        )

    def _collection_isolation(self, case: AdversarialCase) -> AdversarialObservation:
        allowed = self._create_collection("collection-allowed")
        forbidden = self._create_collection("collection-forbidden")
        allowed_uri = "benchmark://adversarial/collection/allowed"
        forbidden_uri = "benchmark://adversarial/collection/forbidden"
        self._ingest_text(
            collection_id=allowed,
            canonical_uri=allowed_uri,
            text="orion sentinel alpha collection evidence",
        )
        self._ingest_text(
            collection_id=forbidden,
            canonical_uri=forbidden_uri,
            text="orion sentinel forbidden collection evidence",
        )

        hits = self._search("orion sentinel", (allowed,))
        uris = tuple(hit.canonical_uri for hit in hits)
        collections = tuple(str(hit.metadata.get("collection_id") or "") for hit in hits)
        passed = bool(hits) and allowed_uri in uris and forbidden_uri not in uris
        passed = passed and set(collections) == {allowed}
        return self._observation(
            case,
            passed,
            returned_hits=len(hits),
            forbidden_hits=sum(1 for uri in uris if uri == forbidden_uri),
            returned_collection_count=len(set(collections)),
        )

    def _tenant_isolation(self, case: AdversarialCase) -> AdversarialObservation:
        protected = self._create_collection(
            "tenant-protected",
            allowed_consumers=("tenant-b",),
        )
        uri = "benchmark://adversarial/tenant/protected"
        self._ingest_text(
            collection_id=protected,
            canonical_uri=uri,
            text="tenant sentinel protected evidence",
        )

        denied = False
        try:
            self._search("tenant sentinel", (protected,), consumer="tenant-a")
        except CollectionAccessDenied:
            denied = True

        authorized_hits = self._search(
            "tenant sentinel",
            (protected,),
            consumer="tenant-b",
        )
        authorized = any(hit.canonical_uri == uri for hit in authorized_hits)
        return self._observation(
            case,
            denied and authorized,
            unauthorized_denied=denied,
            authorized_hits=len(authorized_hits),
        )

    def _duplicate_content(self, case: AdversarialCase) -> AdversarialObservation:
        first = self._create_collection("duplicate-a")
        second = self._create_collection("duplicate-b")
        shared_uri = "https://benchmark.invalid/adversarial/shared"
        for collection_id in (first, second):
            self._ingest_text(
                collection_id=collection_id,
                canonical_uri=shared_uri,
                text="duplicate sentinel canonical evidence",
            )

        hits = self._search("duplicate sentinel", (first, second))
        shared_count = sum(1 for hit in hits if hit.canonical_uri == shared_uri)
        source_collections = {
            str(hit.metadata.get("collection_id") or "")
            for hit in hits
            if hit.canonical_uri == shared_uri
        }
        return self._observation(
            case,
            shared_count == 1,
            canonical_uri_occurrences=shared_count,
            winning_collection_count=len(source_collections),
        )

    def _conflicting_evidence(self, case: AdversarialCase) -> AdversarialObservation:
        first = self._create_collection("conflict-a")
        second = self._create_collection("conflict-b")
        first_uri = "benchmark://adversarial/conflict/deadline-10"
        second_uri = "benchmark://adversarial/conflict/deadline-15"
        self._ingest_text(
            collection_id=first,
            canonical_uri=first_uri,
            text="conflict sentinel contract delivery deadline 10 days",
        )
        self._ingest_text(
            collection_id=second,
            canonical_uri=second_uri,
            text="conflict sentinel contract delivery deadline 15 days",
        )

        hits = self._search(
            "conflict sentinel contract delivery deadline",
            (first, second),
        )
        uris = {hit.canonical_uri for hit in hits}
        evidence_uris = {
            evidence.canonical_uri
            for hit in hits
            for evidence in hit.evidence
        }
        both_sources = {first_uri, second_uri} <= uris
        both_evidence = {first_uri, second_uri} <= evidence_uris
        return self._observation(
            case,
            both_sources and both_evidence,
            returned_conflicting_sources=len({first_uri, second_uri} & uris),
            evidence_sources=len({first_uri, second_uri} & evidence_uris),
        )

    def _stale_source(self, case: AdversarialCase) -> AdversarialObservation:
        collection = self._create_collection("stale")
        uri = "https://benchmark.invalid/adversarial/stale"
        result = self._ingest_text(
            collection_id=collection,
            canonical_uri=uri,
            text="stale sentinel last known evidence",
            source_type="url",
        )
        resource_id = result.resource.resource_id
        original_hash = result.resource.content_hash
        self.service.configure_resource_refresh(
            resource_id,
            interval_seconds=300,
            missing_after_failures=2,
        )

        with patch(
            "arvectum_data.api.service.ingest_url",
            side_effect=OSError("synthetic refresh failure"),
        ):
            first = self.service.refresh_resource(resource_id)
            second = self.service.refresh_resource(resource_id)

        hits = self._search("stale sentinel", (collection,))
        retained = any(hit.canonical_uri == uri for hit in hits)
        with self.service._require_factory()() as session:
            row = session.get(ResourceRow, resource_id)
            if row is None:
                return self._observation(case, False, resource_missing=True)
            status = row.status
            content_hash_unchanged = row.content_hash == original_hash

        passed = (
            first.outcome == "refresh_error"
            and second.outcome == "stale"
            and status == "stale"
            and retained
            and content_hash_unchanged
        )
        return self._observation(
            case,
            passed,
            first_failure_status=first.outcome,
            second_failure_status=second.outcome,
            resource_status=status,
            last_known_evidence_retained=retained,
            content_hash_unchanged=content_hash_unchanged,
        )
