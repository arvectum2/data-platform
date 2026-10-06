from __future__ import annotations

import json
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence
from unittest.mock import patch

from ..api.config import Settings
from ..api.service import DataPlatformService
from ..documents import ingest_file


@dataclass(frozen=True, slots=True)
class SyncScenario:
    scenario_id: str
    changed_resources: tuple[str, ...]
    expected_changed: int
    expected_indexed: int

    def __post_init__(self) -> None:
        if not self.scenario_id.strip():
            raise ValueError("scenario_id must not be blank")
        if self.expected_changed < 0 or self.expected_indexed < 0:
            raise ValueError("expected counts must be non-negative")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SyncScenario":
        return cls(
            scenario_id=str(payload["id"]),
            changed_resources=tuple(str(item) for item in payload.get("changed_resources") or ()),
            expected_changed=int(payload["expected_changed"]),
            expected_indexed=int(payload["expected_indexed"]),
        )


@dataclass(frozen=True, slots=True)
class SyncEfficiencySuite:
    name: str
    resource_count: int
    scenarios: tuple[SyncScenario, ...]
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SyncEfficiencySuite":
        raw = payload.get("scenarios")
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise ValueError("scenarios must be a list")
        metadata = dict(payload.get("metadata") or {})
        resource_count = int(metadata.get("resource_count", 0))
        scenarios = tuple(SyncScenario.from_dict(item) for item in raw)
        if resource_count < 1:
            raise ValueError("metadata.resource_count must be positive")
        if not scenarios:
            raise ValueError("suite must contain at least one scenario")
        ids = [item.scenario_id for item in scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("scenario IDs must be unique")
        return cls(
            name=str(payload["name"]),
            description=str(payload.get("description") or ""),
            metadata=metadata,
            resource_count=resource_count,
            scenarios=scenarios,
        )


@dataclass(frozen=True, slots=True)
class SyncScenarioResult:
    scenario_id: str
    total_resources: int
    changed_resources: int
    indexed_resources: int
    embeddings_written: int
    unchanged_resources: int
    unnecessary_indexed_resources: int
    passed: bool

    @property
    def reprocess_rate(self) -> float:
        return self.indexed_resources / self.total_resources

    @property
    def change_rate(self) -> float:
        return self.changed_resources / self.total_resources

    @property
    def indexing_amplification(self) -> float:
        if self.changed_resources == 0:
            return 0.0 if self.indexed_resources == 0 else float("inf")
        return self.indexed_resources / self.changed_resources


@dataclass(frozen=True, slots=True)
class SyncEfficiencySummary:
    suite_name: str
    scenarios: int
    pass_rate: float
    unnecessary_indexed_resources: int
    total_changed_resources: int
    total_indexed_resources: int
    indexing_amplification: float
    results: tuple[SyncScenarioResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_name": self.suite_name,
            "scenarios": self.scenarios,
            "pass_rate": self.pass_rate,
            "unnecessary_indexed_resources": self.unnecessary_indexed_resources,
            "total_changed_resources": self.total_changed_resources,
            "total_indexed_resources": self.total_indexed_resources,
            "indexing_amplification": self.indexing_amplification,
            "results": [
                {
                    "scenario_id": item.scenario_id,
                    "total_resources": item.total_resources,
                    "changed_resources": item.changed_resources,
                    "indexed_resources": item.indexed_resources,
                    "embeddings_written": item.embeddings_written,
                    "unchanged_resources": item.unchanged_resources,
                    "unnecessary_indexed_resources": item.unnecessary_indexed_resources,
                    "reprocess_rate": item.reprocess_rate,
                    "change_rate": item.change_rate,
                    "indexing_amplification": item.indexing_amplification,
                    "passed": item.passed,
                }
                for item in self.results
            ],
        }


def load_sync_efficiency_suite(path: Path) -> SyncEfficiencySuite:
    return SyncEfficiencySuite.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _candidate(
    *,
    collection_id: str,
    canonical_uri: str,
    text: str,
):
    with tempfile.NamedTemporaryFile(suffix=".txt") as handle:
        handle.write(text.encode("utf-8"))
        handle.flush()
        return ingest_file(
            handle.name,
            collection_id=collection_id,
            source_type="url",
            canonical_uri=canonical_uri,
            title=canonical_uri.rsplit("/", 1)[-1],
            pre_chunked=True,
        )


class PostgresSyncEfficiencyRunner:
    resource_names = ("resource-a", "resource-b", "resource-c")

    def __init__(
        self,
        *,
        database_url: str,
        suite: SyncEfficiencySuite,
        namespace: str | None = None,
    ) -> None:
        if suite.resource_count != len(self.resource_names):
            raise ValueError("suite resource_count does not match runner fixture")
        self.suite = suite
        self.namespace = namespace or uuid.uuid4().hex[:10]
        self.collection_id = f"benchmark:sync:{self.namespace}"
        self.service = DataPlatformService(
            Settings(
                environment="test",
                log_level="WARNING",
                database_url=database_url,
                internal_api_key="sync-benchmark-internal",
                embedding_provider="hashing",
                embedding_model="sync-efficiency-v1-hash",
                embedding_dimension=32,
                embedding_retry_max_attempts=1,
                embedding_retry_base_delay_seconds=0,
                embedding_retry_max_delay_seconds=0,
                allow_private_fetches=True,
            )
        )
        self.service.create_collection(
            collection_id=self.collection_id,
            owner="dp-bench-002",
            name="Sync efficiency benchmark",
            default_language="simple",
        )
        self.urls = {
            name: f"https://benchmark.invalid/sync/{self.namespace}/{name}"
            for name in self.resource_names
        }
        self.versions = {name: 1 for name in self.resource_names}
        self.resource_ids: dict[str, str] = {}
        self._seed()

    def _text(self, name: str) -> str:
        return f"{name} benchmark content version {self.versions[name]}"

    def _build(self, name: str):
        return _candidate(
            collection_id=self.collection_id,
            canonical_uri=self.urls[name],
            text=self._text(name),
        )

    def _seed(self) -> None:
        for name in self.resource_names:
            candidate = self._build(name)
            self.resource_ids[name] = candidate.resource.resource_id
            self.service._persist_and_index(candidate)
            self.service.configure_resource_refresh(
                candidate.resource.resource_id,
                interval_seconds=300,
                missing_after_failures=2,
            )

    def _candidate_for_url(self, url: str, **_: Any):
        name = next(name for name, value in self.urls.items() if value == url)
        return self._build(name)

    def run(self) -> SyncEfficiencySummary:
        results: list[SyncScenarioResult] = []
        for scenario in self.suite.scenarios:
            unknown = set(scenario.changed_resources) - set(self.resource_names)
            if unknown:
                raise ValueError(f"unknown changed resources: {sorted(unknown)}")
            for name in scenario.changed_resources:
                self.versions[name] += 1

            indexed_resource_ids: list[str] = []
            original = self.service._persist_and_index

            def tracking(candidate):
                indexed_resource_ids.append(candidate.resource.resource_id)
                return original(candidate)

            with (
                patch("arvectum_data.api.service.ingest_url", side_effect=self._candidate_for_url),
                patch.object(self.service, "_persist_and_index", side_effect=tracking),
            ):
                refresh_results = [
                    self.service.refresh_resource(self.resource_ids[name])
                    for name in self.resource_names
                ]

            changed = sum(1 for item in refresh_results if item.changed)
            indexed = len(indexed_resource_ids)
            embeddings_written = sum(
                int(item.detail.get("embeddings_written", 0))
                for item in refresh_results
                if item.changed
            )
            expected_changed_ids = {
                self.resource_ids[name] for name in scenario.changed_resources
            }
            unnecessary = sum(
                1
                for resource_id in indexed_resource_ids
                if resource_id not in expected_changed_ids
            )
            unchanged = sum(1 for item in refresh_results if item.outcome == "unchanged")
            passed = (
                changed == scenario.expected_changed
                and indexed == scenario.expected_indexed
                and unnecessary == 0
                and set(indexed_resource_ids) == expected_changed_ids
                and unchanged == len(self.resource_names) - scenario.expected_changed
            )
            results.append(
                SyncScenarioResult(
                    scenario_id=scenario.scenario_id,
                    total_resources=len(self.resource_names),
                    changed_resources=changed,
                    indexed_resources=indexed,
                    embeddings_written=embeddings_written,
                    unchanged_resources=unchanged,
                    unnecessary_indexed_resources=unnecessary,
                    passed=passed,
                )
            )

        total_changed = sum(item.changed_resources for item in results)
        total_indexed = sum(item.indexed_resources for item in results)
        unnecessary = sum(item.unnecessary_indexed_resources for item in results)
        amplification = (
            total_indexed / total_changed
            if total_changed
            else 0.0
        )
        return SyncEfficiencySummary(
            suite_name=self.suite.name,
            scenarios=len(results),
            pass_rate=sum(1 for item in results if item.passed) / len(results),
            unnecessary_indexed_resources=unnecessary,
            total_changed_resources=total_changed,
            total_indexed_resources=total_indexed,
            indexing_amplification=amplification,
            results=tuple(results),
        )
