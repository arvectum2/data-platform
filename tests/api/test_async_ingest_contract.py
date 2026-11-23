"""Fail-closed disabled-by-default async ingest contract, without a database."""

from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from arvectum_data.api.app import create_app
from arvectum_data.api.config import Settings
from arvectum_data.api.operation_metrics import operation_name


def test_async_document_upload_is_disabled_without_explicit_opt_in() -> None:
    settings = Settings(
        _env_file=None, internal_api_key="internal-only", async_ingest_enabled=False
    )
    client = TestClient(create_app(settings))
    h = {"X-Arvectum-Key": "internal-only", "Idempotency-Key": "safe-idempotency-123"}
    payload = {"collection_id": "synthetic:disabled"}
    data = {"file": ("synthetic.txt", b"small synthetic example", "text/plain")}
    assert client.post("/v1/ingest/jobs", data=payload, files=data, headers=h).status_code == 503
    assert client.post("/v1/ingest/jobs", data=payload, files=data, headers={}).status_code == 401
    report = client.get("/v1/support/ingest-jobs", headers={"X-Arvectum-Key": "internal-only"})
    assert report.status_code == 200
    assert report.json() == {"status": "disabled", "scope": "async_ingest_only"}
    assert client.get("/v1/support/ingest-jobs").status_code == 401
    assert operation_name("POST", "/v1/ingest/jobs") is None
    assert operation_name("POST", "/v1/ingest/document") == "ingest"


def test_async_worker_guardrails_are_bounded_and_disabled_by_default() -> None:
    settings = Settings(_env_file=None)
    assert settings.async_ingest_enabled is False
    assert settings.async_ingest_max_bytes <= settings.max_upload_bytes
    assert settings.async_ingest_max_active_jobs <= 128
    assert settings.async_ingest_heartbeat_seconds * 3 < settings.async_ingest_lease_seconds
    for args in (
        {"async_ingest_max_bytes": 10_000_001},
        {"async_ingest_max_active_jobs": 0},
        {"async_ingest_max_global_jobs": 0},
        {"async_ingest_max_global_queued_bytes": 0},
        {"async_ingest_heartbeat_seconds": 60, "async_ingest_lease_seconds": 120},
    ):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **args)
