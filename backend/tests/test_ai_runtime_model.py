"""Reasoning configuration and serialized provider requests, without network IO."""

import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import HumanMessage

from app.lib.ai_runtime.model import ModelConfigurationError, build_runtime_model
from app.lib.settings import Settings


def _config(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        **{
            "ai_provider": "openai",
            "ai_model": "gpt-5.6-luna",
            "ai_api_key": "test-provider-key",
            "ai_base_url": "https://provider.example/v1",
            "ai_reasoning_effort": "",
            **overrides,
        },
    )


@pytest.mark.parametrize("effort", ["none", "minimal", "low", "medium", "high", "xhigh", "max"])
@pytest.mark.parametrize("streaming", [False, True])
def test_reasoning_effort_reaches_chat_completions(monkeypatch, effort, streaming):
    requests: list[httpx.Request] = []

    def send(_client, request, **kwargs):
        requests.append(request)
        payload = json.loads(request.content)
        completion = {
            "id": "chatcmpl-test",
            "created": 0,
            "model": payload["model"],
            "object": "chat.completion.chunk" if streaming else "chat.completion",
            "choices": [{
                "index": 0,
                "delta" if streaming else "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }],
        }
        if streaming:
            return httpx.Response(
                200,
                request=request,
                headers={"content-type": "text/event-stream"},
                content=f"data: {json.dumps(completion)}\n\ndata: [DONE]\n\n",
            )
        return httpx.Response(200, request=request, json=completion)

    monkeypatch.setattr(httpx.Client, "send", send)
    model, _ = build_runtime_model(_config(ai_reasoning_effort=effort), streaming=streaming)
    try:
        if streaming:
            assert "".join(chunk.content for chunk in model.stream("Reply ok")) == "ok"
        else:
            assert model.invoke("Reply ok").content == "ok"
    finally:
        model.http_client.close()

    assert len(requests) == 1
    assert requests[0].url.path == "/v1/chat/completions"
    payload = json.loads(requests[0].content)
    assert payload["reasoning_effort"] == effort
    assert payload["stream"] is streaming
    assert "reasoning" not in payload


@pytest.mark.parametrize("effort", ["", "   ", None])
@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_empty_reasoning_effort_preserves_provider_defaults(effort, provider):
    model, _ = build_runtime_model(_config(ai_provider=provider, ai_reasoning_effort=effort))
    try:
        payload = model._get_request_payload([HumanMessage(content="Reply ok")])
        assert "reasoning_effort" not in payload
        assert "thinking" not in payload
    finally:
        if provider == "openai":
            model.http_client.close()


def test_missing_reasoning_setting_preserves_existing_callers():
    config = SimpleNamespace(
        ai_provider="openai", ai_model="gpt-4o-mini", ai_api_key="test-provider-key",
    )
    model, _ = build_runtime_model(config)
    try:
        assert "reasoning_effort" not in model._get_request_payload([HumanMessage(content="ok")])
    finally:
        model.http_client.close()


def test_reasoning_effort_loads_from_environment(monkeypatch):
    monkeypatch.setenv("AI_REASONING_EFFORT", " HIGH ")
    config = Settings(_env_file=None)
    assert config.ai_reasoning_effort == "high"


def test_invalid_reasoning_effort_fails_before_provider_request():
    with pytest.raises(ModelConfigurationError, match="AI_REASONING_EFFORT must be"):
        build_runtime_model(_config(ai_reasoning_effort="unsupported-value"))


def test_anthropic_rejects_openai_reasoning_effort():
    with pytest.raises(ModelConfigurationError, match="AI_REASONING_EFFORT requires AI_PROVIDER=openai"):
        build_runtime_model(_config(ai_provider="anthropic", ai_reasoning_effort="high"))
