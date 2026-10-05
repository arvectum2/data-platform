from datetime import UTC, datetime

import pytest

from arvectum_data.sync import RefreshPolicy


def test_refresh_policy_is_bounded_and_schedules_next_run():
    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    policy = RefreshPolicy(interval_seconds=3600, missing_after_failures=2)
    assert policy.next_at(now).isoformat() == "2026-10-05T13:00:00+00:00"
    assert policy.as_dict()["missing_after_failures"] == 2


def test_disabled_refresh_policy_has_no_next_run():
    assert RefreshPolicy(enabled=False).next_at() is None


def test_refresh_policy_rejects_busy_loop():
    with pytest.raises(ValueError, match="at least 300"):
        RefreshPolicy(interval_seconds=60)
