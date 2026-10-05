from __future__ import annotations

import json
import urllib.error

import pytest

from arvectum_data.models import (
    GenerationRequest,
    ModelLocality,
    ModelPolicy,
    ModelProviderUnavailable,
    ModelRole,
    ModelRouter,
    OpenAICompatibleProvider,
    RoleConfig,
    VisionRequest,
)


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return None
    def read(self):
        return json.dumps(self.payload).encode()


def test_roles_are_disabled_by_default():
    router = ModelRouter.build(reasoning=RoleConfig(), vision=RoleConfig())
    assert router.provider(ModelRole.REASONING) is None
    assert router.provider(ModelRole.VISION) is None
    assert router.readiness()["reasoning"].enabled is False


def test_local_only_rejects_remote_provider():
    config = RoleConfig(policy=ModelPolicy.LOCAL_ONLY, locality=ModelLocality.REMOTE, model="x", base_url="https://example.test/v1")
    with pytest.raises(ValueError, match="local-only"):
        ModelRouter.build(reasoning=config, vision=RoleConfig())


def test_remote_requires_explicit_allowlist():
    config = RoleConfig(policy=ModelPolicy.REMOTE_ALLOWLIST, locality=ModelLocality.REMOTE, provider="openai-compatible", model="x", base_url="https://example.test/v1")
    with pytest.raises(ValueError, match="allowlist"):
        ModelRouter.build(reasoning=config, vision=RoleConfig())


def test_remote_allowlist_enables_only_named_provider():
    config = RoleConfig(policy=ModelPolicy.REMOTE_ALLOWLIST, locality=ModelLocality.REMOTE, provider="openai-compatible", remote_allowlist=("example.test",), model="x", base_url="https://example.test/v1")
    router = ModelRouter.build(reasoning=config, vision=RoleConfig())
    assert router.provider(ModelRole.REASONING).descriptor.locality == ModelLocality.REMOTE


def test_reasoning_request_uses_openai_compatible_contract(monkeypatch):
    captured = {}
    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        return FakeResponse({"choices": [{"message": {"content": "answer"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 1}})
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleProvider(role=ModelRole.REASONING, model="local-reasoner", base_url="http://127.0.0.1:9000/v1", locality=ModelLocality.LOCAL)
    result = provider.generate(GenerationRequest(prompt="hello"))
    assert result.text == "answer"
    assert captured["body"]["model"] == "local-reasoner"
    assert provider.metrics.snapshot().usage["prompt_tokens"] == 3


def test_vision_request_contains_image(monkeypatch):
    captured = {}
    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        return FakeResponse({"choices": [{"message": {"content": "seen"}}]})
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleProvider(role=ModelRole.VISION, model="local-vlm", base_url="http://127.0.0.1:9001/v1", locality=ModelLocality.LOCAL)
    assert provider.analyze(VisionRequest(prompt="read", image_url="data:image/png;base64,AA==")).text == "seen"
    content = captured["body"]["messages"][-1]["content"]
    assert content[1]["image_url"]["url"].startswith("data:image/png")


def test_failure_does_not_fallback_to_another_provider(monkeypatch):
    calls = []
    def failing(request, timeout):
        calls.append(request.full_url)
        raise urllib.error.URLError("down")
    monkeypatch.setattr("urllib.request.urlopen", failing)
    provider = OpenAICompatibleProvider(role=ModelRole.REASONING, model="local", base_url="http://127.0.0.1:9000/v1", locality=ModelLocality.LOCAL, retry_max_attempts=2, retry_base_delay_seconds=0)
    with pytest.raises(ModelProviderUnavailable):
        provider.generate(GenerationRequest(prompt="hello"))
    assert calls == ["http://127.0.0.1:9000/v1/chat/completions"] * 2
    assert provider.metrics.snapshot().errors == 1


def test_probe_reports_readiness_without_prompt_content(monkeypatch):
    def fake_urlopen(request, timeout):
        assert request.full_url.endswith("/models")
        assert request.data is None
        return FakeResponse({"data": [{"id": "local"}]})
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleProvider(role=ModelRole.REASONING, model="local", base_url="http://127.0.0.1:9000/v1", locality=ModelLocality.LOCAL)
    status = provider.probe()
    assert status.ready is True
    assert status.descriptor.model == "local"


def test_local_only_rejects_non_loopback_endpoint_even_if_marked_local():
    config = RoleConfig(
        policy=ModelPolicy.LOCAL_ONLY,
        locality=ModelLocality.LOCAL,
        model="x",
        base_url="https://models.example.test/v1",
    )
    with pytest.raises(ValueError, match="loopback"):
        ModelRouter.build(reasoning=config, vision=RoleConfig())
