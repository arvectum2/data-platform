from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

from ..acquisition import AcquisitionError
from .models import ConnectorPolicy


T = TypeVar("T")


class ConnectorExecutor:
    def __init__(
        self,
        policy: ConnectorPolicy | None = None,
        *,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.policy = policy or ConnectorPolicy()
        self._sleep = sleeper
        self._clock = clock
        self._last_call_at: float | None = None

    def run(self, operation: Callable[[], T]) -> T:
        self._respect_rate_limit()
        last_error: Exception | None = None
        for attempt in range(1, self.policy.max_attempts + 1):
            try:
                result = operation()
                self._last_call_at = self._clock()
                return result
            except (AcquisitionError, OSError, TimeoutError) as exc:
                last_error = exc
                self._last_call_at = self._clock()
                if attempt >= self.policy.max_attempts:
                    raise
                delay = self.policy.delay_after(attempt)
                if delay:
                    self._sleep(delay)
        assert last_error is not None
        raise last_error

    def _respect_rate_limit(self) -> None:
        if self._last_call_at is None or self.policy.min_interval_s <= 0:
            return
        elapsed = self._clock() - self._last_call_at
        remaining = self.policy.min_interval_s - elapsed
        if remaining > 0:
            self._sleep(remaining)
