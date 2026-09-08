"""Harness contract, error translation and diagnostics (offline, T10-T13).

Covers the C2 contract layer WITHOUT any network or database:

* T10 fingerprint semantics — semantic changes move the fingerprint,
  non-semantic values (keys, log paths, PIDs, attempt timing) never do, and
  the same configuration is stable across processes;
* T11 injected models never borrow global settings as their run identity;
* error translation — deterministic configuration errors stop automatic
  repetition, transient errors stay bounded-retryable, unknown program
  errors are never silently retryable;
* T12 sensitive sentinels inside provider messages, causes and headers never
  reach diagnostics records or business failure messages;
* diagnostics record shape, correlation ids and the JSONL file sink.
"""

from __future__ import annotations

import json
import logging

import pytest
from langchain_core.exceptions import (
    ModelAuthenticationError,
    ModelConnectionError,
    ModelInvalidRequestError,
    ModelNotFoundError,
    ModelPermissionDeniedError,
    ModelRateLimitError,
    ModelTimeoutError,
)

from app.lib.ai_runtime import diagnostics as diag
from app.lib.ai_runtime.adapters import (
    DeepAgentRubricGenerator,
    RubricGenerationResult,
    translate_provider_error,
)
from app.lib.ai_runtime.contract import (
    HARNESS_POLICY_VERSION,
    RESPONSES_HISTORY_POLICY,
    resolve_harness_contract,
    result_schema_hash,
)
from app.lib.ai_runtime.deep_runtime import RuntimeBudget
from app.lib.settings import Settings
from tests import helpers
from tests.test_deep_runtime import IDENTITY, ScriptedModel


def _config(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        **{
            "ai_provider": "openai",
            "ai_model": "gpt-5.6-luna",
            "ai_api_key": "test-provider-key",
            "ai_base_url": "https://provider.example/v1",
            "ai_reasoning_effort": "medium",
            **overrides,
        },
    )


# ---------------------------------------------------------------------------
# T10: fingerprint semantics
# ---------------------------------------------------------------------------

def _contract(config: Settings, **kwargs) -> object:
    return resolve_harness_contract(config, result_schema=RubricGenerationResult, **kwargs)


def test_fingerprint_stable_for_same_configuration():
    a = _contract(_config())
    b = _contract(_config())
    assert a.fingerprint == b.fingerprint
    # Canonical JSON hash: deterministic across processes (no PID, no time).
    assert len(a.fingerprint) == 64


@pytest.mark.parametrize("overrides", [
    {"ai_openai_api": "chat_completions"},          # protocol change
    {"ai_reasoning_effort": "high"},                # effort change
    {"ai_reasoning_effort": ""},                    # effort removed
    {"ai_model": "gpt-5.6-sol"},                    # model change
    {"ai_base_url": "https://other.example/v1"},    # endpoint change
])
def test_semantic_changes_move_fingerprint(overrides):
    base = _contract(_config()).fingerprint
    moved = _contract(_config(**overrides)).fingerprint
    assert moved != base, overrides


def test_budget_and_revision_changes_move_fingerprint():
    base = _contract(_config()).fingerprint
    tightened = _contract(_config(), budget=RuntimeBudget(max_model_calls=1)).fingerprint
    assert tightened != base
    looser_revisions = _contract(_config(), max_revisions=2).fingerprint
    assert looser_revisions != base


def test_credential_rotation_does_not_move_fingerprint():
    before = _contract(_config(ai_api_key="key-one")).fingerprint
    after = _contract(_config(ai_api_key="key-two")).fingerprint
    assert before == after


def test_contract_never_contains_secrets_or_urls():
    contract = _contract(_config())
    blob = json.dumps(contract.canonical_dict(), ensure_ascii=False)
    assert "test-provider-key" not in blob
    assert "provider.example" not in blob
    assert contract.endpoint_fingerprint  # non-secret identity is present


def test_contract_carries_target_combination_identity():
    contract = _contract(_config())
    assert contract.protocol == "responses"
    assert contract.reasoning_effort == "medium"
    assert contract.output_strategy == "provider_strategy_json_schema"
    assert contract.responses_history_policy == RESPONSES_HISTORY_POLICY
    assert contract.harness_policy_version == HARNESS_POLICY_VERSION
    assert contract.result_schema_hash == result_schema_hash(RubricGenerationResult)
    assert contract.sdk_versions["deepagents"]
    # Budgets record the ACTUAL values in force.
    assert contract.max_model_calls == RuntimeBudget().max_model_calls


def test_empty_effort_distinct_from_explicit_none_in_contract():
    unspecified = _contract(_config(ai_reasoning_effort=""))
    explicit_none = _contract(_config(ai_reasoning_effort="none"))
    assert unspecified.reasoning_effort == ""
    assert explicit_none.reasoning_effort == "none"
    assert unspecified.fingerprint != explicit_none.fingerprint


def test_anthropic_contract_shape():
    contract = _contract(_config(
        ai_provider="anthropic", ai_model="claude-sonnet-4-6", ai_reasoning_effort="",
    ))
    assert contract.protocol == "anthropic_messages"
    assert contract.output_strategy == "model_profile_default"
    assert contract.responses_history_policy == "not_applicable"


def test_invalid_protocol_fails_contract_resolution():
    from app.lib.ai_runtime.model import ModelConfigurationError

    with pytest.raises(ModelConfigurationError):
        _contract(_config(ai_openai_api="websocket"))


# ---------------------------------------------------------------------------
# T11: injected models never borrow global identity
# ---------------------------------------------------------------------------

def test_injected_model_requires_explicit_contract():
    with pytest.raises(ValueError, match="伪造运行身份"):
        DeepAgentRubricGenerator(
            model=ScriptedModel(messages=iter([])), identity=IDENTITY,
        )


def test_injected_contract_requires_model():
    with pytest.raises(ValueError, match="注入合同必须伴随注入模型"):
        DeepAgentRubricGenerator(contract=helpers.stub_harness_contract())


def test_injected_contract_is_the_recorded_identity(monkeypatch):
    """Even when global settings describe a DIFFERENT runtime, the injected
    contract is what the generator reports — no settings-derived faking."""
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_MODEL", "totally-different-model")
    stub_contract = helpers.stub_harness_contract(model="scripted-model")
    generator = DeepAgentRubricGenerator(
        model=ScriptedModel(messages=iter([])),
        identity=IDENTITY,
        contract=stub_contract,
    )
    assert generator.harness_contract is stub_contract
    assert generator.harness_contract.model == "scripted-model"
    assert "totally-different-model" not in generator.harness_contract.fingerprint


def test_production_generator_resolves_contract_from_config():
    generator = DeepAgentRubricGenerator(config=_config())
    contract = generator.harness_contract
    assert contract.model == "gpt-5.6-luna"
    assert contract.protocol == "responses"
    assert contract.fingerprint == _contract(_config()).fingerprint


# ---------------------------------------------------------------------------
# Error translation (T07/T08/T09 semantics at the adapter boundary)
# ---------------------------------------------------------------------------

def test_invalid_request_400_is_deterministic_and_non_retryable():
    """The incident case: HTTP 400 param=reasoning_effort must NOT consume
    attempts 2 and 3."""
    from types import SimpleNamespace

    provider_error = ModelInvalidRequestError("Function tools with reasoning_effort ...")
    provider_error.response = SimpleNamespace(status_code=400, headers={})
    provider_error.body = {
        "error": {"type": "invalid_request_error", "param": "reasoning_effort"}
    }
    failure = translate_provider_error(provider_error, stage_message="评分维度生成调用失败")
    assert failure.code == "AI_CONFIG_INVALID"
    assert failure.retryable is False
    assert "AI_OPENAI_API" in failure.message
    # The raw provider message never reaches the business failure text.
    assert "Function tools" not in failure.message


@pytest.mark.parametrize("exc_cls", [
    ModelAuthenticationError, ModelPermissionDeniedError, ModelNotFoundError,
])
def test_auth_permission_notfound_are_non_retryable(exc_cls):
    failure = translate_provider_error(exc_cls("denied"), stage_message="x")
    assert failure.code == "AI_CONFIG_INVALID"
    assert failure.retryable is False


@pytest.mark.parametrize("exc_cls", [
    ModelRateLimitError, ModelTimeoutError, ModelConnectionError,
])
def test_transient_errors_stay_retryable(exc_cls):
    failure = translate_provider_error(exc_cls("busy"), stage_message="生成轮")
    assert failure.code == "AI_CALL_FAILED"
    assert failure.retryable is True


def test_structured_output_validation_is_retryable_content_error():
    from langchain.agents.structured_output import StructuredOutputValidationError

    exc = StructuredOutputValidationError("RubricGenerationResult", ValueError("锚点"), None)
    failure = translate_provider_error(exc, stage_message="生成轮")
    assert failure.code == "AI_OUTPUT_INVALID"
    assert failure.retryable is True


def test_unknown_program_error_is_not_silently_retryable():
    failure = translate_provider_error(ZeroDivisionError("boom"), stage_message="生成轮")
    assert failure.code == "AI_CALL_FAILED"
    assert failure.retryable is False


def test_wrapped_cause_chain_is_classified_through_the_wrapper():
    """LangChain wraps provider SDK errors; the classification must see the
    real category through __cause__ instead of degrading to unknown."""
    wrapper = RuntimeError("agent run failed")
    wrapper.__cause__ = ModelRateLimitError("429")
    failure = translate_provider_error(wrapper, stage_message="生成轮")
    assert failure.code == "AI_CALL_FAILED"
    assert failure.retryable is True


# ---------------------------------------------------------------------------
# T12 + diagnostics record shape
# ---------------------------------------------------------------------------

def test_diagnostics_never_leak_sentinels_from_provider_errors():
    from types import SimpleNamespace

    provider_error = ModelInvalidRequestError(
        "KEY-SENTINEL sk-live-abc材料正文 MATERIAL-SENTINEL"
    )
    provider_error.response = SimpleNamespace(
        status_code=400, headers={"x-request-id": "req_123"}
    )
    provider_error.body = {"error": {"param": "reasoning_effort"}}
    record = diag.build_diagnostic_record(
        event="ai_failure", stage="generate", exception=provider_error,
        contract=_contract(_config()), operation_id="op-1", question_id="q-1",
        attempt=2, thread_id="qgen-q-1-r1",
    )
    blob = json.dumps(record, ensure_ascii=False)
    assert "KEY-SENTINEL" not in blob
    assert "sk-live-abc" not in blob
    assert "MATERIAL-SENTINEL" not in blob
    # Correlation and classification ARE present (R5: actionable diagnostics).
    assert record["http_status"] == 400
    assert record["param"] == "reasoning_effort"
    assert record["request_id"] == "req_123"
    assert record["category"] == "model_invalid_request"
    assert record["operation_id"] == "op-1"
    assert record["question_id"] == "q-1"
    assert record["thread_id"] == "qgen-q-1-r1"
    assert record["attempt"] == 2
    assert record["contract_fingerprint"] == _contract(_config()).fingerprint
    assert record["protocol"] == "responses"
    assert record["reasoning_effort"] == "medium"
    assert set(record.keys()) == set(diag.RECORD_FIELDS)


def test_diagnostics_without_contract_records_unavailable():
    record = diag.build_diagnostic_record(event="ai_failure", stage="contract_resolution")
    assert record["contract_fingerprint"] == "unavailable"
    assert record["category"] == "unknown"


def test_business_failure_message_carries_no_provider_text():
    failure = translate_provider_error(
        ModelInvalidRequestError("SECRET-PROVIDER-TEXT"), stage_message="评分维度生成调用失败"
    )
    assert "SECRET-PROVIDER-TEXT" not in failure.message


def test_record_ai_failure_writes_jsonl_and_stderr(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(diag, "storage_root", lambda: tmp_path)
    logger = logging.getLogger(diag.DIAGNOSTICS_LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger._ai_diagnostics_configured = False

    with caplog.at_level(logging.ERROR, logger=diag.DIAGNOSTICS_LOGGER_NAME):
        record = diag.record_ai_failure(
            stage="generate",
            exception=ModelRateLimitError("slow down"),
            contract=_contract(_config()),
            operation_id="op-77",
            question_id="q-77",
            attempt=1,
            thread_id="qgen-q-77-r1",
        )
    assert record["category"] == "rate_limit"
    log_file = tmp_path / "runtime" / "ai-diagnostics.jsonl"
    assert log_file.exists()
    line = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert line["operation_id"] == "op-77"
    assert line["category"] == "rate_limit"
    assert set(line.keys()) == set(diag.RECORD_FIELDS)

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger._ai_diagnostics_configured = False


def test_diagnostics_file_failure_does_not_mask_original_error(tmp_path, monkeypatch):
    def _boom():
        raise OSError("storage tree unwritable")

    monkeypatch.setattr(diag, "storage_root", _boom)
    logger = logging.getLogger(diag.DIAGNOSTICS_LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger._ai_diagnostics_configured = False
    # Must not raise: diagnostics are best-effort, failure semantics unchanged.
    record = diag.record_ai_failure(stage="generate", exception=RuntimeError("x"))
    # A code identifier is safe to record; arbitrary message text never is.
    assert record["category"] == "RuntimeError"
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger._ai_diagnostics_configured = False


def test_diagnostics_survive_alembic_style_logger_disabling(tmp_path, monkeypatch):
    """Migration tooling (alembic fileConfig) disables existing loggers by
    default; operational diagnostics must keep recording anyway."""
    monkeypatch.setattr(diag, "storage_root", lambda: tmp_path)
    logger = logging.getLogger(diag.DIAGNOSTICS_LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger._ai_diagnostics_configured = False
    logger.disabled = True  # exactly what disable_existing_loggers does

    record = diag.record_ai_failure(
        stage="generate", exception=ModelRateLimitError("429"),
        operation_id="op-disabled", question_id="q-disabled",
    )
    assert record["category"] == "rate_limit"
    log_file = tmp_path / "runtime" / "ai-diagnostics.jsonl"
    assert log_file.exists()
    line = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert line["operation_id"] == "op-disabled"

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger._ai_diagnostics_configured = False
