from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from app.lib.ai_runtime.adapters import DeepAgentsCoverageReviewer, production_adapters
from app.lib.ai_runtime.model import ModelConfigurationError, build_runtime_model, runtime_model_identity
from app.lib.settings import PROJECT_ROOT, Settings


def test_relative_storage_root_is_stable_across_entrypoint_working_directories() -> None:
    assert Settings(storage_root=Path("storage")).storage_root == PROJECT_ROOT / "storage"


def _model_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "ai_provider": "openai",
        "ai_model": "compatible-model",
        "ai_api_key": SecretStr("test-secret"),
        "ai_base_url": "https://models.example/v1",
    }
    values.update(overrides)
    return Settings(**values)


def test_openai_compatible_model_is_explicit_and_non_streaming() -> None:
    model, identity = build_runtime_model(_model_settings())

    assert model.__class__.__name__ == "ChatOpenAI"
    assert model.model == "compatible-model"
    assert model.openai_api_base == "https://models.example/v1"
    assert model.streaming is False
    assert model.temperature is None
    assert model.use_responses_api is False
    assert identity.provider == "openai"
    assert identity.registration_key == "openai:compatible-model"


def test_openai_official_endpoint_does_not_inherit_ambient_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "https://unexpected-proxy.example/v1")

    model, _ = build_runtime_model(_model_settings(ai_base_url=""))

    assert model.openai_api_base == "https://api.openai.com/v1"


def test_anthropic_model_uses_messages_client_and_official_endpoint() -> None:
    model, identity = build_runtime_model(
        _model_settings(ai_provider="anthropic", ai_model="claude-sonnet-4-6", ai_base_url="")
    )

    assert model.__class__.__name__ == "ChatAnthropic"
    assert model.model == "claude-sonnet-4-6"
    assert model.anthropic_api_url == "https://api.anthropic.com"
    assert model.streaming is False
    assert model.temperature is None
    assert identity.provider == "anthropic"


def test_anthropic_official_endpoint_does_not_inherit_ambient_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://unexpected-proxy.example")

    model, _ = build_runtime_model(
        _model_settings(ai_provider="anthropic", ai_model="claude-sonnet-4-6", ai_base_url="")
    )

    assert model.anthropic_api_url == "https://api.anthropic.com"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("ai_provider", "", "AI_PROVIDER"),
        ("ai_provider", "gemini", "AI_PROVIDER"),
        ("ai_model", "", "AI_MODEL"),
        ("ai_model", "model:variant", "AI_MODEL"),
        ("ai_model", "model\nvariant", "AI_MODEL"),
        ("ai_api_key", SecretStr(""), "AI_API_KEY"),
        ("ai_base_url", "file:///tmp/model", "AI_BASE_URL"),
        ("ai_base_url", "https://models.example/v1?api_key=secret", "AI_BASE_URL"),
        ("ai_base_url", "http://[bad?api_key=secret", "AI_BASE_URL"),
    ],
)
def test_production_model_configuration_fails_closed(field: str, value: object, message: str) -> None:
    try:
        config = _model_settings(**{field: value})
    except ValidationError as exc:
        assert message in str(exc)
        return

    with pytest.raises(ModelConfigurationError, match=message):
        runtime_model_identity(config)


def test_model_identity_fingerprint_changes_with_provider_model_or_endpoint() -> None:
    first = runtime_model_identity(_model_settings())
    provider_changed = runtime_model_identity(_model_settings(ai_provider="anthropic"))
    model_changed = runtime_model_identity(_model_settings(ai_model="compatible-model-v2"))
    endpoint_changed = runtime_model_identity(_model_settings(ai_base_url="https://other.example/v1"))

    assert len({first.fingerprint, provider_changed.fingerprint, model_changed.fingerprint, endpoint_changed.fingerprint}) == 4


def test_direct_real_adapter_construction_uses_validated_model_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    identity = runtime_model_identity(_model_settings())
    monkeypatch.setattr(
        "app.lib.ai_runtime.adapters.build_runtime_model",
        lambda: (sentinel, identity),
    )

    adapter = DeepAgentsCoverageReviewer()

    assert adapter._model() is sentinel
    assert adapter._model_spec == identity.registration_key


def test_injected_adapter_requires_explicit_registration_key() -> None:
    with pytest.raises(ModelConfigurationError, match="registration key"):
        DeepAgentsCoverageReviewer(model=object())


def test_production_adapters_require_a_checkpointer() -> None:
    with pytest.raises(RuntimeError, match="checkpointer"):
        production_adapters(None, model=object(), model_spec="openai:test-model")


def test_provider_smoke_failure_does_not_print_exception_details_or_api_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts import smoke_ai_provider

    monkeypatch.setattr(smoke_ai_provider.settings, "ai_runtime_mode", "production")
    monkeypatch.setattr(smoke_ai_provider.settings, "ai_provider", "openai")
    monkeypatch.setattr(smoke_ai_provider.settings, "ai_model", "test-model")
    monkeypatch.setattr(smoke_ai_provider, "build_runtime_model", lambda: (_ for _ in ()).throw(RuntimeError("top-secret")))

    assert smoke_ai_provider.main() == 1
    output = capsys.readouterr()
    assert "top-secret" not in output.err
    assert "AI_PROVIDER_SMOKE=FAIL provider=openai model=test-model error=RuntimeError" in output.err
