from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence


BenchmarkVisibility = Literal["public", "private-derived"]


@dataclass(frozen=True, slots=True)
class BenchmarkSuiteSpec:
    suite_id: str
    file: str
    sha256: str
    case_count: int
    visibility: BenchmarkVisibility
    dimensions: tuple[str, ...]
    thresholds: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.suite_id.strip():
            raise ValueError("suite_id must not be blank")
        if not self.file.strip():
            raise ValueError("file must not be blank")
        if len(self.sha256) != 64 or any(ch not in "0123456789abcdef" for ch in self.sha256):
            raise ValueError("sha256 must be a lowercase hexadecimal digest")
        if self.case_count < 1:
            raise ValueError("case_count must be positive")
        if self.visibility not in {"public", "private-derived"}:
            raise ValueError(f"unsupported visibility: {self.visibility}")
        if not self.dimensions:
            raise ValueError("dimensions must not be empty")
        for metric, threshold in self.thresholds.items():
            if not metric.strip():
                raise ValueError("threshold metric must not be blank")
            if float(threshold) < 0:
                raise ValueError("threshold values must be non-negative")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BenchmarkSuiteSpec":
        return cls(
            suite_id=str(payload["id"]),
            file=str(payload["file"]),
            sha256=str(payload["sha256"]),
            case_count=int(payload["case_count"]),
            visibility=str(payload["visibility"]),  # type: ignore[arg-type]
            dimensions=tuple(str(item) for item in payload["dimensions"]),
            thresholds={
                str(key): float(value)
                for key, value in dict(payload.get("thresholds") or {}).items()
            },
        )


@dataclass(frozen=True, slots=True)
class BenchmarkCatalog:
    version: int
    suites: tuple[BenchmarkSuiteSpec, ...]
    description: str = ""

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("catalog version must be positive")
        if not self.suites:
            raise ValueError("catalog must contain at least one suite")
        ids = [suite.suite_id for suite in self.suites]
        if len(ids) != len(set(ids)):
            raise ValueError("benchmark suite IDs must be unique")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BenchmarkCatalog":
        raw_suites = payload.get("suites")
        if not isinstance(raw_suites, Sequence) or isinstance(raw_suites, (str, bytes)):
            raise ValueError("suites must be a list")
        return cls(
            version=int(payload["version"]),
            description=str(payload.get("description") or ""),
            suites=tuple(BenchmarkSuiteSpec.from_dict(item) for item in raw_suites),
        )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_benchmark_catalog(path: Path) -> BenchmarkCatalog:
    return BenchmarkCatalog.from_dict(json.loads(path.read_text(encoding="utf-8")))


def validate_benchmark_catalog(path: Path) -> BenchmarkCatalog:
    catalog = load_benchmark_catalog(path)
    base_dir = path.parent

    for spec in catalog.suites:
        suite_path = (base_dir / spec.file).resolve()
        if not suite_path.is_relative_to(base_dir.resolve()):
            raise ValueError(f"benchmark path escapes catalog directory: {spec.file}")
        if not suite_path.is_file():
            raise ValueError(f"benchmark file does not exist: {spec.file}")
        actual_hash = file_sha256(suite_path)
        if actual_hash != spec.sha256:
            raise ValueError(
                f"benchmark digest mismatch for {spec.suite_id}: "
                f"expected {spec.sha256}, got {actual_hash}"
            )
        payload = json.loads(suite_path.read_text(encoding="utf-8"))
        cases = payload.get("cases")
        if not isinstance(cases, list):
            raise ValueError(f"benchmark cases must be a list: {spec.file}")
        if len(cases) != spec.case_count:
            raise ValueError(
                f"benchmark case count mismatch for {spec.suite_id}: "
                f"expected {spec.case_count}, got {len(cases)}"
            )
    return catalog
