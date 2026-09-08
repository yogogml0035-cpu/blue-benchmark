"""Wire-protocol contract tests for the model factory, without network IO.

Covers the T-matrix offline layer for protocol choice:

* the default OpenAI protocol is native Responses with client-held encrypted
  reasoning history (``store=false``, no ``previous_response_id``);
* explicit ``chat_completions`` keeps the native Chat Completions shape —
  it is a configuration choice, never a post-failure fallback;
* reasoning effort semantics: empty omits the parameter entirely, explicit
  ``none`` is sent, and the two are never conflated;
* both protocols go through the SDK's native dispatch for sync invoke and
  streaming — no Chat-only ``_generate`` subclass survives anywhere;
* Anthropic keeps the Messages protocol and ignores ``AI_OPENAI_API``.
"""

import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import HumanMessage

from app.lib.ai_runtime.model import (
    ModelConfigurationError,
    build_runtime_model,
    openai_protocol,
)
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


def _responses_body(model: str, text: str = "ok") -> dict:
    return {
        "id": "resp_test_1",
        "object": "response",
        "created_at": 0,
        "model": model,
        "status": "completed",
        "output": [{
            "type": "message",
            "id": "msg_test_1",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        }],
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    }


def _responses_sse(model: str, text: str = "ok") -> str:
    response = _responses_body(model, text)
    created = {**response, "status": "in_progress", "output": []}
    events = [
        ("response.created", {"type": "response.created", "response": created}),
        ("response.in_progress", {"type": "response.in_progress", "response": created}),
        ("response.output_item.added", {
            "type": "response.output_item.added", "output_index": 0,
            "item": response["output"][0],
        }),
        ("response.content_part.added", {
            "type": "response.content_part.added", "item_id": "msg_test_1",
            "output_index": 0, "content_index": 0,
            "part": {"type": "output_text", "text": "", "annotations": []},
        }),
        ("response.output_text.delta", {
            "type": "response.output_text.delta", "item_id": "msg_test_1",
            "output_index": 0, "content_index": 0, "delta": text,
        }),
        ("response.output_text.done", {
            "type": "response.output_text.done", "item_id": "msg_test_1",
            "output_index": 0, "content_index": 0, "text": text,
        }),
        ("response.content_part.done", {
            "type": "response.content_part.done", "item_id": "msg_test_1",
            "output_index": 0, "content_index": 0,
            "part": {"type": "output_text", "text": text, "annotations": []},
        }),
        ("response.output_item.done", {
            "type": "response.output_item.done", "output_index": 0,
            "item": response["output"][0],
        }),
        ("response.completed", {"type": "response.completed", "response": response}),
    ]
    return "".join(
        f"event: {name}\ndata: {json.dumps(payload)}\n\n" for name, payload in events
    )


def _chat_body(model: str, streaming: bool, text: str = "ok") -> dict:
    return {
        "id": "chatcmpl-test",
        "created": 0,
        "model": model,
        "object": "chat.completion.chunk" if streaming else "chat.completion",
        "choices": [{
            "index": 0,
            "delta" if streaming else "message": {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }],
    }


def _intercept(monkeypatch, requests: list[httpx.Request], wire_headers: list[dict] | None = None):
    """Capture wire requests; answer per protocol shape (offline).

    Replaces ``httpx.Client.send`` but STILL runs the client's request and
    response event hooks, exactly like the real transport — otherwise the
    factory's telemetry-header stripping (and its post-send restoration of
    the SDK-internal raw-response flag) would never be exercised. When
    ``wire_headers`` is provided, an immutable snapshot of the headers AS
    SENT is recorded there (the request object itself is mutated again by
    the response hook after the send).
    """

    def send(self, request, **kwargs):
        for hook in self.event_hooks.get("request", []):
            hook(request)
        requests.append(request)
        if wire_headers is not None:
            wire_headers.append({k.lower(): v for k, v in request.headers.items()})
        payload = json.loads(request.content)
        if request.url.path.endswith("/responses"):
            if payload.get("stream"):
                response = httpx.Response(
                    200, request=request,
                    headers={"content-type": "text/event-stream"},
                    content=_responses_sse(payload["model"]),
                )
            else:
                response = httpx.Response(
                    200, request=request, json=_responses_body(payload["model"])
                )
        else:
            streaming = bool(payload.get("stream"))
            body = _chat_body(payload["model"], streaming)
            if streaming:
                response = httpx.Response(
                    200, request=request,
                    headers={"content-type": "text/event-stream"},
                    content=f"data: {json.dumps(body)}\n\ndata: [DONE]\n\n",
                )
            else:
                response = httpx.Response(200, request=request, json=body)
        for hook in self.event_hooks.get("response", []):
            hook(response)
        return response

    monkeypatch.setattr(httpx.Client, "send", send)


def _text_of(content) -> str:
    """Public text of a message content that may be a list of blocks."""

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") in ("text", "output_text")
        )
    return ""


# ---------------------------------------------------------------------------
# Protocol choice
# ---------------------------------------------------------------------------

def test_default_openai_protocol_is_responses():
    assert openai_protocol(_config()) == "responses"
    assert openai_protocol(_config(ai_openai_api="")) == "responses"
    assert openai_protocol(SimpleNamespace()) == "responses"


def test_invalid_openai_protocol_rejected_before_any_request():
    with pytest.raises(ModelConfigurationError, match="AI_OPENAI_API must be"):
        build_runtime_model(_config(ai_openai_api="grpc"))


@pytest.mark.parametrize("streaming", [False, True])
def test_responses_protocol_native_request_shape(monkeypatch, streaming):
    requests: list[httpx.Request] = []
    _intercept(monkeypatch, requests)
    model, _ = build_runtime_model(
        _config(ai_reasoning_effort="medium"), streaming=streaming
    )
    try:
        if streaming:
            assert "".join(
                _text_of(chunk.content) for chunk in model.stream("Reply ok")
            ) == "ok"
        else:
            assert _text_of(model.invoke("Reply ok").content) == "ok"
    finally:
        model.http_client.close()

    assert len(requests) == 1
    assert requests[0].url.path == "/v1/responses"
    payload = json.loads(requests[0].content)
    # Responses-native shapes: input (not messages), reasoning.effort (not
    # top-level reasoning_effort), client-held encrypted history.
    assert payload["reasoning"] == {"effort": "medium"}
    assert "reasoning_effort" not in payload
    assert "messages" not in payload
    assert isinstance(payload["input"], list)
    assert payload["store"] is False
    assert payload["include"] == ["reasoning.encrypted_content"]
    assert "previous_response_id" not in payload or payload["previous_response_id"] is None
    assert payload["stream"] is streaming


@pytest.mark.parametrize("streaming", [False, True])
def test_explicit_chat_completions_protocol_native_request_shape(monkeypatch, streaming):
    requests: list[httpx.Request] = []
    _intercept(monkeypatch, requests)
    model, _ = build_runtime_model(
        _config(ai_openai_api="chat_completions", ai_reasoning_effort="medium"),
        streaming=streaming,
    )
    try:
        if streaming:
            assert "".join(
                _text_of(chunk.content) for chunk in model.stream("Reply ok")
            ) == "ok"
        else:
            assert _text_of(model.invoke("Reply ok").content) == "ok"
    finally:
        model.http_client.close()

    assert len(requests) == 1
    assert requests[0].url.path == "/v1/chat/completions"
    payload = json.loads(requests[0].content)
    assert payload["reasoning_effort"] == "medium"
    # Responses-only fields must never leak into the Chat protocol.
    for responses_field in ("reasoning", "input", "store", "include",
                            "previous_response_id"):
        assert responses_field not in payload
    assert isinstance(payload["messages"], list)
    assert payload["stream"] is streaming


@pytest.mark.parametrize("effort", ["none", "minimal", "low", "medium", "high", "xhigh", "max"])
def test_every_effort_value_reaches_responses_protocol(monkeypatch, effort):
    requests: list[httpx.Request] = []
    _intercept(monkeypatch, requests)
    model, _ = build_runtime_model(_config(ai_reasoning_effort=effort))
    try:
        model.invoke("Reply ok")
    finally:
        model.http_client.close()
    payload = json.loads(requests[0].content)
    assert payload["reasoning"] == {"effort": effort}


# ---------------------------------------------------------------------------
# Effort semantics: empty omits, explicit none sends
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("protocol", ["responses", "chat_completions"])
@pytest.mark.parametrize("effort", ["", "   ", None])
def test_empty_reasoning_effort_omits_parameter(effort, protocol):
    model, _ = build_runtime_model(
        _config(ai_openai_api=protocol, ai_reasoning_effort=effort)
    )
    try:
        payload = model._get_request_payload([HumanMessage(content="Reply ok")])
        assert "reasoning_effort" not in payload
        assert "reasoning" not in payload
        assert "thinking" not in payload
    finally:
        model.http_client.close()


@pytest.mark.parametrize("protocol", ["responses", "chat_completions"])
def test_explicit_none_effort_is_sent_and_distinct_from_empty(protocol):
    model, _ = build_runtime_model(
        _config(ai_openai_api=protocol, ai_reasoning_effort="none")
    )
    try:
        payload = model._get_request_payload([HumanMessage(content="Reply ok")])
        if protocol == "responses":
            assert payload["reasoning"] == {"effort": "none"}
        else:
            assert payload["reasoning_effort"] == "none"
    finally:
        model.http_client.close()


def test_missing_reasoning_setting_preserves_existing_callers():
    config = SimpleNamespace(
        ai_provider="openai", ai_model="gpt-4o-mini", ai_api_key="test-provider-key",
    )
    model, _ = build_runtime_model(config)
    try:
        payload = model._get_request_payload([HumanMessage(content="ok")])
        assert "reasoning_effort" not in payload
        assert "reasoning" not in payload
        # Legacy callers without the protocol field still get the default.
        assert openai_protocol(config) == "responses"
    finally:
        model.http_client.close()


def test_reasoning_effort_loads_from_environment(monkeypatch):
    monkeypatch.setenv("AI_REASONING_EFFORT", " HIGH ")
    config = Settings(_env_file=None)
    assert config.ai_reasoning_effort == "high"


def test_openai_api_loads_and_normalizes_from_environment(monkeypatch):
    monkeypatch.setenv("AI_OPENAI_API", " Chat_Completions ")
    config = Settings(_env_file=None)
    assert config.ai_openai_api == "chat_completions"


def test_invalid_reasoning_effort_fails_before_provider_request():
    with pytest.raises(ModelConfigurationError, match="AI_REASONING_EFFORT must be"):
        build_runtime_model(_config(ai_reasoning_effort="unsupported-value"))


# ---------------------------------------------------------------------------
# Native SDK dispatch: no Chat-only subclass survives
# ---------------------------------------------------------------------------

def test_openai_model_is_native_sdk_class_without_generate_override():
    from langchain_openai import ChatOpenAI

    model, _ = build_runtime_model(_config(ai_reasoning_effort="medium"))
    try:
        assert type(model) is ChatOpenAI
        assert "_generate" not in type(model).__dict__
        assert model.use_responses_api is True
    finally:
        model.http_client.close()

    chat_model, _ = build_runtime_model(_config(ai_openai_api="chat_completions"))
    try:
        assert type(chat_model) is ChatOpenAI
        assert "_generate" not in type(chat_model).__dict__
        assert chat_model.use_responses_api is False
    finally:
        chat_model.http_client.close()


@pytest.mark.parametrize("protocol", ["responses", "chat_completions"])
def test_telemetry_headers_stripped_on_both_protocols(monkeypatch, protocol):
    requests: list[httpx.Request] = []
    wire: list[dict] = []
    _intercept(monkeypatch, requests, wire_headers=wire)
    model, _ = build_runtime_model(_config(ai_openai_api=protocol))
    try:
        model.invoke("Reply ok")
    finally:
        model.http_client.close()
    sent = wire[0]
    assert not any(h.startswith("x-stainless-") for h in sent)
    assert "user-agent" not in sent


# ---------------------------------------------------------------------------
# Anthropic boundary
# ---------------------------------------------------------------------------

def test_anthropic_rejects_openai_reasoning_effort():
    with pytest.raises(ModelConfigurationError, match="AI_REASONING_EFFORT requires AI_PROVIDER=openai"):
        build_runtime_model(_config(ai_provider="anthropic", ai_reasoning_effort="high"))


@pytest.mark.parametrize("protocol_setting", ["responses", "chat_completions", ""])
def test_anthropic_ignores_openai_protocol_setting(protocol_setting):
    model, identity = build_runtime_model(
        _config(ai_provider="anthropic", ai_model="claude-sonnet-4-6",
                ai_openai_api=protocol_setting)
    )
    from langchain_anthropic import ChatAnthropic

    assert isinstance(model, ChatAnthropic)
    assert identity.provider == "anthropic"
    # No Responses/Chat fields leak into the Messages-protocol construction.
    assert getattr(model, "use_responses_api", None) is None
