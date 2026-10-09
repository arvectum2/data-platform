"""Isolated tests: never invoke launchctl or alter production runtime."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import pytest

MODULE = Path(__file__).resolve().parents[1] / "scripts/ops/macmini_llm_profile.py"
spec = importlib.util.spec_from_file_location("macmini_llm_profile", MODULE)
assert spec and spec.loader
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)


def test_quality_env_preserves_credentials_and_other_providers():
    content = (
        "ARVECTUM_DATA_INTERNAL_API_KEY=test-secret\n"
        "ARVECTUM_DATA_REASONING_MODEL=older\n"
        "ARVECTUM_DATA_REASONING_BASE_URL=http://127.0.0.1:8081/v1\n"
        "ARVECTUM_DATA_EMBEDDING_DIMENSION=2560\n"
    )
    result = manager.configured_env(content, "quality")
    assert "ARVECTUM_DATA_INTERNAL_API_KEY=test-secret" in result
    assert "ARVECTUM_DATA_REASONING_MODEL=arvectum-gemma4-12b-it-qat-q4_0" in result
    assert "ARVECTUM_DATA_EMBEDDING_DIMENSION=2560" in result
    assert "ARVECTUM_DATA_MODEL_MAX_CONCURRENCY=1" in result


def test_fast_env_keeps_dimension_and_locality():
    inp = "ARVECTUM_DATA_EMBEDDING_DIMENSION=2560\n"
    out = manager.configured_env(inp, "fast")
    assert "qwen3.5-4b-mlx-4bit" in out
    assert "ARVECTUM_DATA_REASONING_BASE_URL=http://127.0.0.1:8081/v1" in out
    assert "ARVECTUM_DATA_EMBEDDING_DIMENSION=2560" in out


def test_atomic_profile_read_write(tmp_path, monkeypatch):
    profile = tmp_path / ".llm-profile"
    monkeypatch.setattr(manager, "PROFILE", profile)
    assert manager.current() == "quality"
    manager.put(profile, "fast\n")
    assert manager.current() == "fast"
    manager.put(profile, "incorrect\n")
    with pytest.raises(ValueError):
        manager.current()
    assert profile.stat().st_mode & 0o077 == 0


def test_models_distinct():
    assert manager.PROFILES["quality"][0] != manager.PROFILES["fast"][0]
