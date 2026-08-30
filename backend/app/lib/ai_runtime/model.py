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

from pydantic import SecretStr

from app.lib.settings import Settings, settings


_OPENAI_OFFICIAL_BASE_URL = "https://api.openai.com/v1"
_ANTHROPIC_OFFICIAL_BASE_URL = "https://api.anthropic.com"


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
    def fingerprint(self) -> str:
        """Short non-secret identity used to version Checkpoint compatibility."""

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
    base_url = normalize_base_url(getattr(config, "ai_base_url", ""))
    api_key = _secret_value(getattr(config, "ai_api_key", ""))
    if require_credentials and (not api_key or api_key.lower().startswith("replace-with-")):
        raise ModelConfigurationError("AI_API_KEY must be configured")
    return RuntimeModelIdentity(provider=provider, model=model, base_url=base_url)


def build_runtime_model(
    config: Settings | object = settings,
) -> tuple[Any, RuntimeModelIdentity]:
    """Build the configured LangChain chat model and its safe identity."""

    identity = runtime_model_identity(config)
    api_key = _secret_value(getattr(config, "ai_api_key", ""))
    kwargs: dict[str, Any] = {
        "api_key": api_key,
        "streaming": False,
        "max_retries": int(getattr(config, "ai_model_retries", 1)),
    }
    if identity.provider == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ModelConfigurationError("langchain-openai dependency is unavailable") from None

        # OpenAI-compatible vendors expose the Chat Completions contract, not
        # necessarily the newer Responses API.  Force the protocol explicitly
        # so a model name that LangChain classifies as Responses-preferred
        # cannot silently switch the wire format.
        kwargs["base_url"] = identity.base_url or _OPENAI_OFFICIAL_BASE_URL
        kwargs["use_responses_api"] = False
        return ChatOpenAI(model=identity.model, **kwargs), identity

    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        raise ModelConfigurationError("langchain-anthropic dependency is unavailable") from None

    kwargs["base_url"] = identity.base_url or _ANTHROPIC_OFFICIAL_BASE_URL
    return ChatAnthropic(model_name=identity.model, **kwargs), identity


# Descriptive aliases keep call sites and deployment scripts readable while
# preserving one implementation and one validation contract.
create_runtime_model = build_runtime_model
build_model = build_runtime_model


__all__ = [
    "ModelConfigurationError",
    "RuntimeModelIdentity",
    "build_model",
    "build_runtime_model",
    "create_runtime_model",
    "normalize_base_url",
    "runtime_model_identity",
]
