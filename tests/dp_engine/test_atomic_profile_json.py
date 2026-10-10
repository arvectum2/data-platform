"""Atomic snapshot utility stays compatible across both profile stores."""

import json

import pytest

from arvectum_data.storage import atomic_json


def test_atomic_json_preserves_russian_sorted_human_readable_snapshot(tmp_path):
    path = tmp_path / "nested" / "profile.json"
    atomic_json.write_atomic_json(path, {"z": "Русский", "a": [2, 1]})
    assert path.read_text(encoding="utf-8") == (
        '{\n  "a": [\n    2,\n    1\n  ],\n  "z": "Русский"\n}\n'
    )
    assert json.loads(path.read_text(encoding="utf-8"))["z"] == "Русский"
    assert not list(path.parent.glob(".*.tmp"))


def test_atomic_json_failed_replace_keeps_previous_snapshot_and_cleans_temp(tmp_path, monkeypatch):
    path = tmp_path / "profile.json"
    atomic_json.write_atomic_json(path, {"value": "old"})
    before = path.read_bytes()

    def fail_replace(*_args):
        raise OSError("simulated destination failure")

    monkeypatch.setattr(atomic_json.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated"):
        atomic_json.write_atomic_json(path, {"value": "new"})
    assert path.read_bytes() == before
    assert sorted(path.parent.glob(".profile.json.*.tmp")) == []
