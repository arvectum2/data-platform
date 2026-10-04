from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .models import EvaluationCase


class EvaluationRequestError(RuntimeError):
    pass


@dataclass(slots=True)
class HttpSearchRunner:
    base_url: str
    api_key: str = ""
    consumer: str = ""
    consumer_key: str = ""
    timeout_seconds: float = 30.0

    def __call__(
        self,
        case: EvaluationCase,
    ) -> tuple[list[dict[str, Any]], float]:
        payload = {
            "query": case.query,
            "collections": list(case.collections),
            "limit": case.limit,
            "mode": case.mode,
            "lexical_weight": case.lexical_weight,
            "vector_weight": case.vector_weight,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-Arvectum-Key"] = self.api_key
        if self.consumer or self.consumer_key:
            if not self.consumer or not self.consumer_key:
                raise EvaluationRequestError(
                    "consumer and consumer_key must be configured together"
                )
            headers["X-Arvectum-Consumer"] = self.consumer
            headers["X-Arvectum-Consumer-Key"] = self.consumer_key
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/v1/search",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                body = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise EvaluationRequestError(
                f"search returned HTTP {exc.code}: {detail}"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise EvaluationRequestError(
                f"search request failed: {type(exc).__name__}"
            ) from exc
        latency_ms = (time.perf_counter() - started) * 1000.0
        hits = body.get("hits")
        if not isinstance(hits, list):
            raise EvaluationRequestError("search response contains invalid hits payload")
        return [item for item in hits if isinstance(item, dict)], latency_ms
