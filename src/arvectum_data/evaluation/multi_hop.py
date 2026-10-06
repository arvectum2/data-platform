from __future__ import annotations

import json
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..api.config import Settings
from ..api.service import DataPlatformService
from ..documents import ingest_file


@dataclass(frozen=True, slots=True)
class MultiHopScenario:
    scenario_id: str
    start: str
    target: str
    max_depth: int
    expected_target_depth: int
    required_relation_types: tuple[str, ...]
    expected_evidence_edges: int

    def __post_init__(self) -> None:
        if not self.scenario_id.strip():
            raise ValueError("scenario_id must not be blank")
        if not self.start.strip() or not self.target.strip():
            raise ValueError("start and target must not be blank")
        if self.max_depth < 2 or self.max_depth > 5:
            raise ValueError("max_depth must be between 2 and 5")
        if self.expected_target_depth < 2 or self.expected_target_depth > self.max_depth:
            raise ValueError("expected_target_depth must be within multi-hop depth")
        if not self.required_relation_types:
            raise ValueError("required_relation_types must not be empty")
        if self.expected_evidence_edges < 1:
            raise ValueError("expected_evidence_edges must be positive")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MultiHopScenario":
        return cls(
            scenario_id=str(payload["id"]),
            start=str(payload["start"]),
            target=str(payload["target"]),
            max_depth=int(payload["max_depth"]),
            expected_target_depth=int(payload["expected_target_depth"]),
            required_relation_types=tuple(str(item) for item in payload["required_relation_types"]),
            expected_evidence_edges=int(payload["expected_evidence_edges"]),
        )


@dataclass(frozen=True, slots=True)
class MultiHopSuite:
    name: str
    scenarios: tuple[MultiHopScenario, ...]
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MultiHopSuite":
        raw = payload.get("scenarios")
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise ValueError("scenarios must be a list")
        scenarios = tuple(MultiHopScenario.from_dict(item) for item in raw)
        if not scenarios:
            raise ValueError("suite must contain at least one scenario")
        ids = [item.scenario_id for item in scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("scenario IDs must be unique")
        return cls(
            name=str(payload["name"]),
            description=str(payload.get("description") or ""),
            metadata=dict(payload.get("metadata") or {}),
            scenarios=scenarios,
        )


@dataclass(frozen=True, slots=True)
class MultiHopScenarioResult:
    scenario_id: str
    target_reached: bool
    target_depth: int | None
    required_relations_found: bool
    evidence_edges: int
    provenance_complete: bool
    passed: bool


@dataclass(frozen=True, slots=True)
class MultiHopSummary:
    suite_name: str
    scenarios: int
    pass_rate: float
    target_recall: float
    provenance_completeness: float
    results: tuple[MultiHopScenarioResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_name": self.suite_name,
            "scenarios": self.scenarios,
            "pass_rate": self.pass_rate,
            "target_recall": self.target_recall,
            "provenance_completeness": self.provenance_completeness,
            "results": [
                {
                    "scenario_id": item.scenario_id,
                    "target_reached": item.target_reached,
                    "target_depth": item.target_depth,
                    "required_relations_found": item.required_relations_found,
                    "evidence_edges": item.evidence_edges,
                    "provenance_complete": item.provenance_complete,
                    "passed": item.passed,
                }
                for item in self.results
            ],
        }


def load_multi_hop_suite(path: Path) -> MultiHopSuite:
    return MultiHopSuite.from_dict(json.loads(path.read_text(encoding="utf-8")))


class PostgresMultiHopRunner:
    def __init__(self, *, database_url: str, suite: MultiHopSuite, namespace: str | None = None) -> None:
        self.suite = suite
        self.namespace = namespace or uuid.uuid4().hex[:10]
        self.collection_id = f"benchmark:multihop:{self.namespace}"
        self.service = DataPlatformService(
            Settings(
                environment="test",
                log_level="WARNING",
                database_url=database_url,
                internal_api_key="multihop-benchmark-internal",
                embedding_provider="hashing",
                embedding_model="multi-hop-v1-hash",
                embedding_dimension=32,
                embedding_retry_max_attempts=1,
                embedding_retry_base_delay_seconds=0,
                embedding_retry_max_delay_seconds=0,
            )
        )
        self.service.create_collection(
            collection_id=self.collection_id,
            owner="dp-bench-002",
            name="Multi-hop evidence benchmark",
            default_language="simple",
        )
        self.entities: dict[str, dict[str, Any]] = {}
        self._seed_graph()

    def _ingest_evidence(self, name: str, text: str) -> str:
        with tempfile.NamedTemporaryFile(suffix=".txt") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            result = ingest_file(
                handle.name,
                collection_id=self.collection_id,
                source_type="benchmark",
                canonical_uri=f"benchmark://multi-hop/{self.namespace}/{name}",
                title=name,
                pre_chunked=True,
            )
        self.service._persist_and_index(result)
        if len(result.chunks) != 1:
            raise RuntimeError("multi-hop fixture must produce exactly one chunk")
        return result.chunks[0].chunk_id

    def _entity(self, key: str, entity_type: str, canonical_name: str, aliases: Sequence[Mapping[str, object]] = ()) -> None:
        self.entities[key] = self.service.create_entity(
            entity_type=entity_type,
            canonical_name=canonical_name,
            aliases=aliases,
        )

    def _relation(self, source: str, target: str, relation_type: str, chunk_id: str) -> None:
        self.service.create_entity_relation(
            source_entity_id=self.entities[source]["entity_id"],
            target_entity_id=self.entities[target]["entity_id"],
            relation_type=relation_type,
            status="canonical",
            chunk_id=chunk_id,
        )

    def _seed_graph(self) -> None:
        contract_chunk = self._ingest_evidence("contract", "Контракт ABC-42 заключен с поставщиком Альфа.")
        inn_chunk = self._ingest_evidence("supplier-inn", "Поставщик Альфа имеет ИНН 7701234567.")
        supplies_chunk = self._ingest_evidence("supplier-product", "Поставщик Альфа поставляет изделие Модуль X.")
        manufacturer_chunk = self._ingest_evidence("product-manufacturer", "Изделие Модуль X выпускает производитель Бета.")
        country_chunk = self._ingest_evidence("manufacturer-country", "Производитель Бета зарегистрирован в России.")

        self._entity("contract", "contract", "Контракт ABC-42", ({"alias_kind":"contract_number","value":"ABC-42"},))
        self._entity("supplier", "supplier", "Альфа")
        self._entity("tax-id", "tax_id", "7701234567", ({"alias_kind":"inn","value":"7701234567"},))
        self._entity("product", "product", "Модуль X")
        self._entity("manufacturer", "manufacturer", "Бета")
        self._entity("country", "country", "Россия")

        self._relation("contract", "supplier", "awarded_to", contract_chunk)
        self._relation("supplier", "tax-id", "has_inn", inn_chunk)
        self._relation("supplier", "product", "supplies", supplies_chunk)
        self._relation("product", "manufacturer", "manufactured_by", manufacturer_chunk)
        self._relation("manufacturer", "country", "registered_in", country_chunk)

    def run(self) -> MultiHopSummary:
        results: list[MultiHopScenarioResult] = []
        for scenario in self.suite.scenarios:
            start_id = self.entities[scenario.start]["entity_id"]
            target_id = self.entities[scenario.target]["entity_id"]
            rows = self.service.traverse_entity_graph(start_id, max_depth=scenario.max_depth, limit=200)
            target_depths = [
                int(row["depth"])
                for row in rows
                if target_id in {row["source_entity_id"], row["target_entity_id"]}
            ]
            target_depth = min(target_depths) if target_depths else None
            required_rows = [row for row in rows if row["relation_type"] in scenario.required_relation_types]
            found_types = {row["relation_type"] for row in required_rows}
            required_relations_found = set(scenario.required_relation_types) <= found_types
            evidence_rows = [
                row
                for row in required_rows
                if row.get("chunk_id")
                and row.get("document_id")
                and row.get("resource_id")
                and row.get("source_collection_id") == self.collection_id
            ]
            evidence_edges = len(evidence_rows)
            provenance_complete = evidence_edges >= scenario.expected_evidence_edges
            target_reached = target_depth == scenario.expected_target_depth
            passed = target_reached and required_relations_found and provenance_complete
            results.append(
                MultiHopScenarioResult(
                    scenario_id=scenario.scenario_id,
                    target_reached=target_reached,
                    target_depth=target_depth,
                    required_relations_found=required_relations_found,
                    evidence_edges=evidence_edges,
                    provenance_complete=provenance_complete,
                    passed=passed,
                )
            )

        count = len(results)
        return MultiHopSummary(
            suite_name=self.suite.name,
            scenarios=count,
            pass_rate=sum(1 for item in results if item.passed) / count,
            target_recall=sum(1 for item in results if item.target_reached) / count,
            provenance_completeness=sum(1 for item in results if item.provenance_complete) / count,
            results=tuple(results),
        )
