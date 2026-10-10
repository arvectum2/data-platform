"""Test cross-worker consumer tenant isolation on real PostgreSQL."""
from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config

from arvectum_data.api.config import Settings
from arvectum_data.api.service import DataPlatformService

pytestmark = pytest.mark.postgres


def _service():
    url = os.getenv("ARVECTUM_DATA_TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("ARVECTUM_DATA_TEST_DATABASE_URL is not configured")
    os.environ["ARVECTUM_DATA_DATABASE_URL"] = url
    command.upgrade(Config("alembic.ini"), "head")
    return DataPlatformService(Settings(
        environment="test", database_url=url, embedding_provider="hashing",
        embedding_model="key-concurrency", embedding_dimension=16,
    ))


def test_two_concurrent_tenant_issuances_cannot_cross_own_same_consumer():
    service = _service()
    consumer = "tenant-lock:" + uuid.uuid4().hex[:10]
    barrier = threading.Barrier(2)

    def issue(tenant):
        barrier.wait(timeout=8)
        try:
            return service.create_consumer_key(consumer_id=consumer, tenant_id=tenant)
        except ValueError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(issue, ("tenant-a", "tenant-b")))
    created = [result for result in results if isinstance(result, dict)]
    rejected = [result for result in results if isinstance(result, ValueError)]
    assert len(created) == 1 and len(rejected) == 1
    assert "already belongs to another active tenant" in str(rejected[0])
    assert service._consumer_tenant(consumer) == created[0]["tenant_id"]


def test_expired_or_revoked_key_does_not_authorize_its_previous_tenant():
    service = _service()
    consumer = "key-lifecycle:" + uuid.uuid4().hex[:10]
    key = service.create_consumer_key(consumer_id=consumer, tenant_id="old-tenant")
    assert service._consumer_tenant(consumer) == "old-tenant"
    service.revoke_consumer_key(key["key_id"])
    assert service._consumer_tenant(consumer) == ""
    replacement = service.create_consumer_key(
        consumer_id=consumer, tenant_id="new-tenant",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    assert replacement["tenant_id"] == "new-tenant"
    assert service._consumer_tenant(consumer) == "new-tenant"
