"""Offline guardrails for the explicitly owner-gated shared Qwen stage."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from arvectum_data.documents import ingest_bytes
from arvectum_data.supportability import percentile


def _module() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "ingest_slo_shared_qwen_window.py"
    scripts = str(path.parent)
    spec = importlib.util.spec_from_file_location("isolated_qwen_window_for_tests", path)
    assert spec is not None and spec.loader is not None
    sys.path.insert(0, scripts)
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(scripts)


def test_stage_corpus_has_realistic_unique_chunks_before_serving() -> None:
    stage = _module()
    assert len(stage.SIZES) == 20
    counts = []
    for index, size in enumerate(stage.SIZES):
        payload = stage.synthetic_bytes(size, index)
        assert 0 < size - len(payload) < 4 or len(payload) == size
        result = ingest_bytes(
            payload,
            filename="synthetic.txt",
            collection_id="preflight:offline",
            canonical_uri=f"synthetic://preflight/{index}",
        )
        counts.append(len(result.chunks))
        assert len({chunk.content_hash for chunk in result.chunks}) == len(result.chunks)
    assert counts == [2] * 9 + [5] * 8 + [10] * 2 + [27]
    assert percentile(counts, 0.5) == 5


def test_periodic_scheduler_is_restored_even_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    stage = _module()
    state = {"disabled": False, "restored": False, "watchdog_stopped": False}

    def fake_sh(*args: str, **_kwargs: object) -> str:
        if args[1] == "print":
            return "state = not running"
        if args[1] == "print-disabled":
            value = "disabled" if state["disabled"] else "enabled"
            return f'"{stage.TA_JOB}" => {value}'
        if args[1] == "disable":
            state["disabled"] = True
            return ""
        if args[1] == "enable":
            state["disabled"] = False
            state["restored"] = True
            return ""
        raise AssertionError("unrecognised mocked launchctl command")

    class FakeWatchdog:
        def __init__(self, *_args: object, **_kwargs: object):
            pass

        def terminate(self) -> None:
            state["watchdog_stopped"] = True

        def wait(self, timeout: int = 0) -> int:
            return 0

    monkeypatch.setattr(stage, "sh", fake_sh)
    monkeypatch.setattr(stage.subprocess, "Popen", FakeWatchdog)
    with pytest.raises(RuntimeError, match="simulated stage failure"):
        with stage.pause_new_runs():
            assert state["disabled"] is True
            raise RuntimeError("simulated stage failure")
    assert state == {"disabled": False, "restored": True, "watchdog_stopped": True}


def test_without_explicit_authorisation_cannot_start_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage = _module()
    monkeypatch.setattr(sys, "argv", ["ingest_slo_shared_qwen_window.py"])
    with pytest.raises(RuntimeError, match="explicit window flag required"):
        stage.main()


def test_failed_restoration_leaves_failsafe_active(monkeypatch: pytest.MonkeyPatch) -> None:
    stage = _module()
    state = {"disabled": False, "watchdog_stopped": False}

    def fake_sh(*args: str, **_kwargs: object) -> str:
        action = args[1]
        if action == "print":
            return "state = not running"
        if action == "print-disabled":
            value = "disabled" if state["disabled"] else "enabled"
            return f'"{stage.TA_JOB}" => {value}'
        if action == "disable":
            state["disabled"] = True
            return ""
        if action == "enable":
            raise RuntimeError("simulated launchctl restoration failure")
        raise AssertionError("unexpected simulated command")

    class FakeWatchdog:
        def __init__(self, *_args: object, **_kwargs: object):
            pass

        def terminate(self) -> None:
            state["watchdog_stopped"] = True

    monkeypatch.setattr(stage, "sh", fake_sh)
    monkeypatch.setattr(stage.subprocess, "Popen", FakeWatchdog)
    with pytest.raises(RuntimeError, match="simulated launchctl restoration failure"):
        with stage.pause_new_runs():
            pass
    assert state == {"disabled": True, "watchdog_stopped": False}
