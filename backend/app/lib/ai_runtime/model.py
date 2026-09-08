"""Explicit model-provider configuration for the production AI runtime.

The Worker is intentionally the only caller that turns this configuration into
a live model.  Keeping validation here prevents each adapter (or a provider
SDK) from making a different guess about which credentials or endpoint to use.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import SecretStr

from app.lib.settings import Settings, settings


_OPENAI_OFFICIAL_BASE_URL = "https://api.openai.com/v1"
_ANTHROPIC_OFFICIAL_BASE_URL = "https://api.anthropic.com"

# The OpenAI wire protocol is an explicit configuration choice. There is no
# automatic fallback: a request rejected by the gateway is a configuration
# fact for the administrator, never a signal to silently switch protocols,
# drop parameters or change models.
OPENAI_PROTOCOL_RESPONSES = "responses"
OPENAI_PROTOCOL_CHAT_COMPLETIONS = "chat_completions"
OPENAI_PROTOCOLS = (OPENAI_PROTOCOL_RESPONSES, OPENAI_PROTOCOL_CHAT_COMPLETIONS)
DEFAULT_OPENAI_PROTOCOL = OPENAI_PROTOCOL_RESPONSES

_REASONING_EFFORT_VALUES = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
)

# Internal openai-SDK header (itself x-stainless-*) that the synchronous
# with_raw_response dispatch relies on AFTER the send; see the transport
# hooks in build_runtime_model.
_RAW_RESPONSE_HEADER = "X-Stainless-Raw-Response"
_RAW_RESPONSE_EXTENSION = "runtime_raw_response_flag"


class ModelConfigurationError(RuntimeError):
    """A safe-to-display production model configuration error."""


@dataclass(frozen=True, slots=True)
class RuntimeModelIdentity:
    """Non-secret identity of the model endpoint used by an AI Profile."""

    provider: str
    model: str
    base_url: str | None

    @property
    def model_spec(self) -> str:
        return f"{self.provider}:{self.model}"

    @property
    def registration_key(self) -> str:
        """The exact model key used for the process-level HarnessProfile."""

        return self.model_spec

    @property
    def endpoint_fingerprint(self) -> str:
        """Short non-secret endpoint identity for diagnostics and contracts.

        Checkpoint compatibility is versioned by the full harness contract
        fingerprint (app.lib.ai_runtime.contract), never by this value alone.
        """

        endpoint = self.base_url or "official"
        return sha256(f"{self.provider}\0{self.model}\0{endpoint}".encode()).hexdigest()[:16]


def _secret_value(value: object) -> str:
    if isinstance(value, SecretStr):
        return value.get_secret_value().strip()
    return str(value or "").strip()


def normalize_base_url(value: str | None) -> str | None:
    """Validate and canonicalize an optional provider HTTP endpoint.

    Base URLs are deliberately not allowed to carry userinfo, query strings,
    or fragments.  Those are common places for an accidental credential to
    leak into logs or profile identity material.
    """

    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = urlsplit(raw)
    except ValueError:
        raise ModelConfigurationError("AI_BASE_URL must be an HTTP(S) URL") from None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ModelConfigurationError("AI_BASE_URL must be an HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ModelConfigurationError("AI_BASE_URL must not contain credentials or query data")
    try:
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ModelConfigurationError("AI_BASE_URL must be an HTTP(S) URL") from exc
    if not host:
        raise ModelConfigurationError("AI_BASE_URL must be an HTTP(S) URL")
    host = host.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    netloc = host if port in {None, default_port} else f"{host}:{port}"
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), netloc, path, "", ""))


def openai_protocol(config: Settings | object) -> str:
    """Resolve the explicit OpenAI wire-protocol choice.

    Empty means the default (Responses). An unknown value fails closed at
    configuration time — before any model, checkpoint or request exists.
    """

    raw = str(getattr(config, "ai_openai_api", "") or "").strip().lower()
    if not raw:
        return DEFAULT_OPENAI_PROTOCOL
    if raw not in OPENAI_PROTOCOLS:
        raise ModelConfigurationError("AI_OPENAI_API must be responses or chat_completions")
    return raw


def validated_reasoning_effort(config: Settings | object) -> str:
    """Normalize and validate the reasoning effort.

    Returns ``""`` for "unspecified" (the model default applies), which is
    DISTINCT from an explicit ``"none"``. Shared by the model factory and the
    harness contract so both always see the same validated value.
    """

    effort = str(getattr(config, "ai_reasoning_effort", "") or "").strip().lower()
    if not effort:
        return ""
    provider = str(getattr(config, "ai_provider", "") or "").strip().lower()
    if provider != "openai":
        raise ModelConfigurationError("AI_REASONING_EFFORT requires AI_PROVIDER=openai")
    if effort not in _REASONING_EFFORT_VALUES:
        raise ModelConfigurationError(
            "AI_REASONING_EFFORT must be empty, none, minimal, low, medium, high, xhigh or max"
        )
    return effort


def runtime_model_identity(
    config: Settings | object = settings,
    *,
    require_credentials: bool = True,
) -> RuntimeModelIdentity:
    """Validate provider/model/base URL and return a non-secret identity.

    ``require_credentials=False`` is used only while constructing the AI
    Profile for API-side business records and deterministic tests.  The live
    Worker always uses the default, fail-closed credential validation.
    """

    provider = str(getattr(config, "ai_provider", "") or "").strip().lower()
    if not provider:
        raise ModelConfigurationError("AI_PROVIDER is required")
    if provider not in {"openai", "anthropic"}:
        raise ModelConfigurationError("AI_PROVIDER must be openai or anthropic")
    model = str(getattr(config, "ai_model", "") or "").strip()
    if not model:
        raise ModelConfigurationError("AI_MODEL is required")
    if ":" in model:
        raise ModelConfigurationError("AI_MODEL must not contain ':'")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in model):
        raise ModelConfigurationError("AI_MODEL must be a single-line identifier")
    base_url = normalize_base_url(getattr(config, "ai_base_url", ""))
    api_key = _secret_value(getattr(config, "ai_api_key", ""))
    if require_credentials and (not api_key or api_key.lower().startswith("replace-with-")):
        raise ModelConfigurationError("AI_API_KEY must be configured")
    return RuntimeModelIdentity(provider=provider, model=model, base_url=base_url)


def build_runtime_model(
    config: Settings | object = settings,
    *,
    streaming: bool = False,
) -> tuple[Any, RuntimeModelIdentity]:
    """Build the configured LangChain chat model and its safe identity.

    ``streaming=True`` enables token streaming on the transport; the deep
    runtime uses it for live progress.

    OpenAI wire protocol (explicit ``AI_OPENAI_API`` configuration, never a
    post-failure fallback):

    * ``responses`` (default): native Responses API. The reasoning effort is
      sent as ``reasoning={"effort": ...}``; history stays client-held
      (``store=false``, no ``previous_response_id``) with encrypted reasoning
      round-trips, so multi-turn tool loops work without server-side session
      state. This is the protocol current OpenAI reasoning models require for
      function tools combined with a reasoning effort.
    * ``chat_completions``: native Chat Completions. An explicit effort is
      sent as top-level ``reasoning_effort``. For gateways that expose only
      that contract, with the combinations they actually accept.

    Anthropic keeps the native Messages protocol; ``AI_OPENAI_API`` is not
    consulted for it.

    Request construction, streaming, message conversion and exception mapping
    all stay inside the official SDK — there is no ``_generate`` override and
    no copied wire-format handling. Only the minimal HTTP configuration the
    current endpoints are known to require (bounded timeout, retry ceiling,
    telemetry-header stripping) is injected through the native client.
    """

    identity = runtime_model_identity(config)
    api_key = _secret_value(getattr(config, "ai_api_key", ""))
    kwargs: dict[str, Any] = {
        "api_key": api_key,
        "streaming": streaming,
        "max_retries": int(getattr(config, "ai_model_retries", 1)),
    }
    reasoning_effort = validated_reasoning_effort(config)
    request_timeout = float(getattr(config, "ai_request_timeout_seconds", 180.0))
    if identity.provider == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ModelConfigurationError("langchain-openai dependency is unavailable") from None

        protocol = openai_protocol(config)
        kwargs["base_url"] = identity.base_url or _OPENAI_OFFICIAL_BASE_URL
        kwargs["request_timeout"] = request_timeout
        kwargs["use_responses_api"] = protocol == OPENAI_PROTOCOL_RESPONSES
        if protocol == OPENAI_PROTOCOL_RESPONSES:
            # Client-held history with encrypted reasoning continuity: the
            # gateway stores nothing, and multi-turn tool rounds round-trip
            # the opaque reasoning items the SDK produces. Verified end to
            # end by the C1 capability gate (see the archived C1 report).
            # THESE THREE KWARGS ARE the contract's RESPONSES_HISTORY_POLICY
            # ("client-held-encrypted-v1"): changing any of them without
            # bumping that constant is a contract violation — the binding is
            # asserted in tests/test_ai_runtime_contract.py.
            kwargs["store"] = False
            kwargs["use_previous_response_id"] = False
            kwargs["include"] = ["reasoning.encrypted_content"]
            if reasoning_effort:
                kwargs["reasoning"] = {"effort": reasoning_effort}
        elif reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort

        def strip_provider_blocked_headers(request: httpx.Request) -> None:
            # The configured OpenAI-compatible gateway rejects the OpenAI SDK
            # telemetry headers.  They are transport metadata, not part of
            # the model contract, and removing them keeps the request
            # equivalent to the documented wire format of either protocol.
            #
            # ONE x-stainless header is an internal SDK contract, not
            # telemetry: ``X-Stainless-Raw-Response`` tells the client's own
            # response handling to return a raw-response wrapper (used by the
            # synchronous ``with_raw_response`` dispatch).  It is removed from
            # the wire like the others, stashed on the request extensions,
            # and restored by the response hook below so the SDK's post-send
            # inspection still sees it.
            raw_response_flag = request.headers.get(_RAW_RESPONSE_HEADER)
            for header in list(request.headers):
                if header.lower().startswith("x-stainless-"):
                    request.headers.pop(header, None)
            request.headers.pop("user-agent", None)
            if raw_response_flag is not None:
                request.extensions[_RAW_RESPONSE_EXTENSION] = raw_response_flag

        def restore_raw_response_flag(response: httpx.Response) -> None:
            flag = response.request.extensions.get(_RAW_RESPONSE_EXTENSION)
            if flag is not None:
                response.request.headers[_RAW_RESPONSE_HEADER] = flag

        kwargs["http_client"] = httpx.Client(
            event_hooks={
                "request": [strip_provider_blocked_headers],
                "response": [restore_raw_response_flag],
            },
        )
        return ChatOpenAI(model=identity.model, **kwargs), identity

    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        raise ModelConfigurationError("langchain-anthropic dependency is unavailable") from None

    kwargs["base_url"] = identity.base_url or _ANTHROPIC_OFFICIAL_BASE_URL
    kwargs["default_request_timeout"] = request_timeout
    return ChatAnthropic(model_name=identity.model, **kwargs), identity


# Descriptive aliases keep call sites and deployment scripts readable while
# preserving one implementation and one validation contract.
create_runtime_model = build_runtime_model
build_model = build_runtime_model


__all__ = [
    "DEFAULT_OPENAI_PROTOCOL",
    "OPENAI_PROTOCOLS",
    "OPENAI_PROTOCOL_CHAT_COMPLETIONS",
    "OPENAI_PROTOCOL_RESPONSES",
    "ModelConfigurationError",
    "RuntimeModelIdentity",
    "build_model",
    "build_runtime_model",
    "create_runtime_model",
    "normalize_base_url",
    "openai_protocol",
    "runtime_model_identity",
    "validated_reasoning_effort",
]
