from __future__ import annotations

import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Sequence

from ..api.config import Settings
from ..api.service import DataPlatformService
from ..search import SearchMode, SearchQuery
from .models import EvaluationCase, EvaluationSuite


_FOOTPRINT_RE = re.compile(r"phys_footprint:\s*(\d+)\s+B")
_FOOTPRINT_PEAK_RE = re.compile(r"phys_footprint_peak:\s*(\d+)\s+B")
_POWER_RE = re.compile(r"CPU Power:\s*([\d.]+)\s*mW")
_GPU_POWER_RE = re.compile(r"GPU Power:\s*([\d.]+)\s*mW")
_GPU_RESIDENCY_RE = re.compile(r"GPU HW active residency:\s*([\d.]+)%")


@dataclass(frozen=True, slots=True)
class ProcessFootprint:
    role: str
    port: int
    pid: int
    cpu_percent: float
    rss_bytes: int
    physical_footprint_bytes: int
    physical_footprint_peak_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "port": self.port,
            "pid": self.pid,
            "cpu_percent": self.cpu_percent,
            "rss_bytes": self.rss_bytes,
            "physical_footprint_bytes": self.physical_footprint_bytes,
            "physical_footprint_peak_bytes": self.physical_footprint_peak_bytes,
        }


@dataclass(frozen=True, slots=True)
class ThroughputResult:
    workers: int
    queries: int
    elapsed_seconds: float
    queries_per_second: float
    top1_accuracy: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "workers": self.workers,
            "queries": self.queries,
            "elapsed_seconds": self.elapsed_seconds,
            "queries_per_second": self.queries_per_second,
            "top1_accuracy": self.top1_accuracy,
        }


@dataclass(frozen=True, slots=True)
class PowerSnapshot:
    cpu_power_mw: float | None
    gpu_power_mw: float | None
    gpu_active_residency_percent: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu_power_mw": self.cpu_power_mw,
            "gpu_power_mw": self.gpu_power_mw,
            "gpu_active_residency_percent": self.gpu_active_residency_percent,
        }


@dataclass(frozen=True, slots=True)
class RuntimeResourceReport:
    host_memory_bytes: int
    gpu_memory_model: str
    dedicated_gpu_memory_bytes: int | None
    processes: tuple[ProcessFootprint, ...]
    throughput: tuple[ThroughputResult, ...]
    power: PowerSnapshot | None = None

    def to_dict(self) -> dict[str, Any]:
        current = sum(item.physical_footprint_bytes for item in self.processes)
        peak = sum(item.physical_footprint_peak_bytes for item in self.processes)
        return {
            "host_memory_bytes": self.host_memory_bytes,
            "gpu_memory_model": self.gpu_memory_model,
            "dedicated_gpu_memory_bytes": self.dedicated_gpu_memory_bytes,
            "process_physical_footprint_bytes": current,
            "process_physical_footprint_peak_sum_bytes": peak,
            "processes": [item.to_dict() for item in self.processes],
            "throughput": [item.to_dict() for item in self.throughput],
            "power": None if self.power is None else self.power.to_dict(),
        }


def parse_footprint(output: str) -> tuple[int, int]:
    current = _FOOTPRINT_RE.search(output)
    peak = _FOOTPRINT_PEAK_RE.search(output)
    if current is None or peak is None:
        raise ValueError("physical footprint fields not found")
    return int(current.group(1)), int(peak.group(1))


def parse_power_snapshot(output: str) -> PowerSnapshot:
    cpu = [float(item) for item in _POWER_RE.findall(output)]
    gpu = [float(item) for item in _GPU_POWER_RE.findall(output)]
    residency = [float(item) for item in _GPU_RESIDENCY_RE.findall(output)]
    return PowerSnapshot(
        cpu_power_mw=None if not cpu else sum(cpu) / len(cpu),
        gpu_power_mw=None if not gpu else sum(gpu) / len(gpu),
        gpu_active_residency_percent=(
            None if not residency else sum(residency) / len(residency)
        ),
    )


def _run(command: Sequence[str]) -> str:
    completed = subprocess.run(
        list(command),
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _pid_for_port(port: int) -> int:
    output = _run(("lsof", f"-tiTCP:{port}", "-sTCP:LISTEN")).strip().splitlines()
    if not output:
        raise RuntimeError(f"no listener on port {port}")
    return int(output[0])


def collect_process_footprint(role: str, port: int) -> ProcessFootprint:
    pid = _pid_for_port(port)
    ps = _run(("ps", "-o", "pcpu=,rss=", "-p", str(pid))).strip().split()
    if len(ps) < 2:
        raise RuntimeError(f"unable to read process stats for pid {pid}")
    footprint = _run(
        ("footprint", "--pid", str(pid), "--noCategories", "-f", "bytes")
    )
    current, peak = parse_footprint(footprint)
    return ProcessFootprint(
        role=role,
        port=port,
        pid=pid,
        cpu_percent=float(ps[0]),
        rss_bytes=int(ps[1]) * 1024,
        physical_footprint_bytes=current,
        physical_footprint_peak_bytes=peak,
    )


def collect_power_snapshot() -> PowerSnapshot:
    output = _run(
        (
            "sudo",
            "-n",
            "powermetrics",
            "-n",
            "1",
            "-i",
            "500",
            "--samplers",
            "cpu_power,gpu_power",
        )
    )
    return parse_power_snapshot(output)


def _request(case: EvaluationCase) -> SearchQuery:
    return SearchQuery(
        query=case.query,
        collections=case.collections,
        limit=case.limit,
        mode=SearchMode(case.mode),
        lexical_weight=case.lexical_weight,
        vector_weight=case.vector_weight,
        query_variants=case.query_variants,
        query_variant_weight=case.query_variant_weight,
        collapse_by_canonical_uri=case.collapse_by_canonical_uri,
    )


def _top1(case: EvaluationCase, hits: Sequence[Any]) -> bool:
    if not hits:
        return False
    value = getattr(hits[0], case.id_field)
    return str(value) in set(case.expected_ids)


def measure_search_throughput(
    settings: Settings,
    suite: EvaluationSuite,
    *,
    consumer: str | None,
    workers: int,
) -> ThroughputResult:
    if workers < 1:
        raise ValueError("workers must be positive")
    service = DataPlatformService(settings)

    def run(case: EvaluationCase) -> bool:
        hits = service.search(_request(case), consumer=consumer)
        return _top1(case, hits)

    started = time.perf_counter()
    if workers == 1:
        outcomes = [run(case) for case in suite.cases]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            outcomes = list(pool.map(run, suite.cases))
    elapsed = time.perf_counter() - started
    return ThroughputResult(
        workers=workers,
        queries=len(outcomes),
        elapsed_seconds=elapsed,
        queries_per_second=len(outcomes) / elapsed,
        top1_accuracy=sum(1 for item in outcomes if item) / len(outcomes),
    )


def collect_runtime_resources(
    settings: Settings,
    suite: EvaluationSuite,
    *,
    consumer: str | None,
    workers: Sequence[int],
    service_port: int = 8094,
    embedding_port: int = 8090,
    reasoning_port: int = 8081,
    sample_power: bool = False,
) -> RuntimeResourceReport:
    host_memory_bytes = int(_run(("sysctl", "-n", "hw.memsize")).strip())
    processes = (
        collect_process_footprint("data-platform", service_port),
        collect_process_footprint("embedding", embedding_port),
        collect_process_footprint("reasoning", reasoning_port),
    )
    throughput = tuple(
        measure_search_throughput(
            settings,
            suite,
            consumer=consumer,
            workers=worker_count,
        )
        for worker_count in workers
    )
    power = collect_power_snapshot() if sample_power else None
    return RuntimeResourceReport(
        host_memory_bytes=host_memory_bytes,
        gpu_memory_model="Apple Silicon unified memory",
        dedicated_gpu_memory_bytes=None,
        processes=processes,
        throughput=throughput,
        power=power,
    )
