from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .models import GenerationRequest, ModelDescriptor, ModelLocality, ModelResponse, ModelRole, ProviderReadiness, VisionRequest


class ModelProviderError(RuntimeError):
    pass


class ModelProviderUnavailable(ModelProviderError):
    pass


class ModelPolicyError(ModelProviderError):
    pass


@runtime_checkable
class TextGenerationProvider(Protocol):
    descriptor: ModelDescriptor
    def generate(self, request: GenerationRequest) -> ModelResponse: ...
    def probe(self) -> ProviderReadiness: ...


@runtime_checkable
class VisionProvider(Protocol):
    descriptor: ModelDescriptor
    def analyze(self, request: VisionRequest) -> ModelResponse: ...
    def probe(self) -> ProviderReadiness: ...


@dataclass(frozen=True)
class ProviderMetricsSnapshot:
    requests: int
    successes: int
    errors: int
    total_latency_ms: float
    usage: dict[str, int]
    errors_by_type: dict[str, int]


class ProviderMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests = self._successes = self._errors = 0
        self._total_latency_ms = 0.0
        self._usage: Counter[str] = Counter()
        self._errors_by_type: Counter[str] = Counter()

    def success(self, latency_ms: float, usage: dict[str, int]) -> None:
        with self._lock:
            self._requests += 1
            self._successes += 1
            self._total_latency_ms += latency_ms
            self._usage.update({k: int(v) for k, v in usage.items() if isinstance(v, int)})

    def error(self, error: Exception, latency_ms: float) -> None:
        with self._lock:
            self._requests += 1
            self._errors += 1
            self._total_latency_ms += latency_ms
            self._errors_by_type[type(error).__name__] += 1

    def snapshot(self) -> ProviderMetricsSnapshot:
        with self._lock:
            return ProviderMetricsSnapshot(self._requests, self._successes, self._errors, round(self._total_latency_ms, 2), dict(self._usage), dict(self._errors_by_type))


class OpenAICompatibleProvider:
    provider_name = "openai-compatible"

    def __init__(self, *, role: ModelRole, model: str, base_url: str, locality: ModelLocality, version: str | None = None, timeout_seconds: float = 60, retry_max_attempts: int = 2, retry_base_delay_seconds: float = 0.25, max_concurrency: int = 2, api_key: str = "") -> None:
        self.descriptor = ModelDescriptor(role, self.provider_name, model, version, locality, ("text-generation", "reasoning") if role == ModelRole.REASONING else ("text-generation", "vision"))
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.retry_max_attempts = retry_max_attempts
        self.retry_base_delay_seconds = retry_base_delay_seconds
        self.api_key = api_key
        self._semaphore = threading.BoundedSemaphore(max_concurrency)
        self.metrics = ProviderMetrics()

    def generate(self, request: GenerationRequest) -> ModelResponse:
        if self.descriptor.role != ModelRole.REASONING:
            raise ModelPolicyError("vision provider cannot serve reasoning requests")
        messages = ([{"role": "system", "content": request.system_prompt}] if request.system_prompt else []) + [{"role": "user", "content": request.prompt}]
        return self._chat(messages, request.max_tokens, request.temperature)

    def analyze(self, request: VisionRequest) -> ModelResponse:
        if self.descriptor.role != ModelRole.VISION:
            raise ModelPolicyError("reasoning provider cannot serve vision requests")
        messages = ([{"role": "system", "content": request.system_prompt}] if request.system_prompt else []) + [{"role": "user", "content": [{"type": "text", "text": request.prompt}, {"type": "image_url", "image_url": {"url": request.image_url}}]}]
        return self._chat(messages, request.max_tokens, request.temperature)

    def _chat(self, messages: list[dict], max_tokens: int, temperature: float) -> ModelResponse:
        started = time.perf_counter()
        try:
            raw = self._request_json("POST", "/chat/completions", {"model": self.descriptor.model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature})
            text = raw["choices"][0]["message"]["content"]
            if not isinstance(text, str):
                raise ModelProviderError("provider returned non-text completion")
            usage = {k: int(v) for k, v in (raw.get("usage") or {}).items() if isinstance(v, int)}
            latency_ms = (time.perf_counter() - started) * 1000
            self.metrics.success(latency_ms, usage)
            return ModelResponse(text, self.descriptor.provider, self.descriptor.model, self.descriptor.version, self.descriptor.locality, round(latency_ms, 2), usage)
        except Exception as exc:
            self.metrics.error(exc, (time.perf_counter() - started) * 1000)
            raise

    def _request_json(self, method: str, path: str, payload: dict | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        last_error: Exception | None = None
        with self._semaphore:
            for attempt in range(self.retry_max_attempts):
                request = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
                try:
                    with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                        decoded = json.loads(response.read().decode("utf-8"))
                    if not isinstance(decoded, dict):
                        raise ModelProviderError("provider returned invalid JSON payload")
                    return decoded
                except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                    last_error = exc
                except urllib.error.HTTPError as exc:
                    if exc.code < 500:
                        raise ModelProviderError(f"provider request failed with HTTP {exc.code}") from exc
                    last_error = exc
                if attempt + 1 < self.retry_max_attempts:
                    time.sleep(self.retry_base_delay_seconds * (2**attempt))
        raise ModelProviderUnavailable("model provider is unavailable") from last_error

    def probe(self) -> ProviderReadiness:
        started = time.perf_counter()
        try:
            self._request_json("GET", "/models")
        except Exception as exc:
            return ProviderReadiness(True, False, self.descriptor, round((time.perf_counter() - started) * 1000, 2), type(exc).__name__)
        return ProviderReadiness(True, True, self.descriptor, round((time.perf_counter() - started) * 1000, 2))
