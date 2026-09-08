"""Offline guard tests for the C1 capability probe.

Proves the C1-AC1 safety contract WITHOUT any network or database access:

* dry-run performs a redacted precheck only and never opens a socket;
* ``--execute`` refuses missing/protected/non-exclusive checkpoint targets
  before any connection attempt;
* the interrupting sink fires only after a durable tool round-trip;
* public-event and evidence redaction gates reject sensitive material;
* the candidate model construction is Responses-native, keeps the reasoning
  effort, and never copies the Chat-only ``_generate`` override.

Every test in this module runs with sockets blocked at the ``socket`` module
level, so an accidental outbound connection is a loud test failure.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import probe_ai_harness_capability as probe


@pytest.fixture(autouse=True)
def block_sockets(monkeypatch):
    def _refuse(*args, **kwargs):
        raise AssertionError("C1 探针离线测试不允许任何 socket 外连")

    monkeypatch.setattr(socket, "socket", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    yield


def _parse(argv: list[str]):
    return probe.build_parser().parse_args(argv)


# ---------------------------------------------------------------------------
# Dry-run: redacted precheck, zero network, zero database
# ---------------------------------------------------------------------------

def test_dry_run_is_default_and_never_touches_network(tmp_path, capsys):
    exit_code = probe.main([
        "--corpus-root", str(tmp_path / "missing-corpus"),
        "--out", str(tmp_path / "out"),
    ])
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "PROBE=DRY_RUN_OK" in captured
    report_text = captured[: captured.index("PROBE=DRY_RUN_OK")]
    report = json.loads(report_text)
    assert report["mode"] == "dry-run"
    assert "不连接任何数据库" in report["database"]
    assert "不发起任何模型请求" in report["network"]
    # A missing corpus is reported as a safe error, never a silent pass or a
    # placeholder substitution.
    assert "error" in report["corpus"]
    # Redaction: no credential-looking material anywhere in the report.
    lowered = captured.lower()
    assert "api_key=" not in lowered
    assert "sk-" not in lowered


def test_dry_run_never_constructs_a_model(tmp_path, monkeypatch):
    def _refuse(*args, **kwargs):
        raise AssertionError("dry-run 不得构造模型")

    monkeypatch.setattr(probe, "build_probe_runtime", _refuse)
    assert probe.main([
        "--corpus-root", str(tmp_path / "missing"),
        "--out", str(tmp_path / "out"),
    ]) == 0


# ---------------------------------------------------------------------------
# --execute configuration gates (checked before any connection)
# ---------------------------------------------------------------------------

def test_execute_requires_explicit_isolated_dsn(monkeypatch, capsys):
    monkeypatch.delenv("C1_CHECKPOINT_DSN", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        probe.main(["--execute"])
    assert excinfo.value.code == 1
    assert "C1_CHECKPOINT_DSN" in capsys.readouterr().out


@pytest.mark.parametrize("dsn", [
    "postgresql://u@127.0.0.1:5432/blue_benchmark",
    "postgresql://u@127.0.0.1:5432/blue_benchmark_checkpoint",
    "postgresql+psycopg://u@127.0.0.1:5432/postgres",
    "postgresql://u@127.0.0.1:5432/template1",
])
def test_execute_refuses_protected_databases(dsn, capsys):
    with pytest.raises(SystemExit) as excinfo:
        probe.main(["--execute", "--checkpoint-dsn", dsn])
    assert excinfo.value.code == 1
    assert "受保护库" in capsys.readouterr().out


def test_execute_refuses_non_exclusive_database(capsys):
    # Any database without the dedicated capability marker is refused, even
    # when it is not one of the project's own databases.
    with pytest.raises(SystemExit) as excinfo:
        probe.main([
            "--execute",
            "--checkpoint-dsn", "postgresql://u@127.0.0.1:5432/some_shared_db",
        ])
    assert excinfo.value.code == 1
    assert "c1_capability" in capsys.readouterr().out


def test_execute_dsn_guard_runs_before_live_connection(monkeypatch):
    # If the name guard ever moved after the connect step, the blocked socket
    # fixture would turn this into a connection AssertionError instead of the
    # clean protected-database refusal.
    with pytest.raises(SystemExit):
        probe.main([
            "--execute",
            "--checkpoint-dsn", "postgresql://u@h:5432/blue_benchmark_checkpoint",
        ])


def test_resolve_config_normalizes_sqlalchemy_suffix(tmp_path):
    args = _parse([
        "--execute",
        "--checkpoint-dsn",
        "postgresql+psycopg://u@127.0.0.1:5432/blue_benchmark_c1_capability",
        "--corpus-root", str(tmp_path),
        "--out", str(tmp_path / "out"),
    ])
    config = probe.resolve_config(args)
    assert config.checkpoint_dsn.startswith("postgresql://")
    assert config.db_name == "blue_benchmark_c1_capability"


# ---------------------------------------------------------------------------
# Interruption point: only after a durable tool round-trip
# ---------------------------------------------------------------------------

def _event(kind, stage=None, text=None, tool=None, detail=None):
    return SimpleNamespace(kind=kind, stage=stage, text=text, tool=tool, detail=detail)


def test_interrupting_sink_fires_only_after_tool_round_trip():
    exits: list[int] = []
    inner = probe.EvidenceSink(t0=0.0)
    sink = probe.InterruptingSink(inner, exit_fn=exits.append)

    # A model call BEFORE any tool round must not interrupt (the checkpoint
    # would not yet contain a tool round-trip).
    sink.emit(_event("stage", stage="model_call_started", detail="call 1"))
    assert exits == []
    sink.emit(_event("tool_started", tool="read_file"))
    assert exits == []
    sink.emit(_event("tool_finished", tool="read_file", detail="ok"))
    assert exits == []
    # First model call after the durable tool round: planned crash point.
    sink.emit(_event("stage", stage="model_call_started", detail="call 2"))
    assert exits == [probe.INTERRUPT_EXIT_CODE]
    # Fires exactly once.
    sink.emit(_event("stage", stage="model_call_started", detail="call 3"))
    assert exits == [probe.INTERRUPT_EXIT_CODE]


def test_evidence_sink_rejects_sensitive_event_fields():
    sink = probe.EvidenceSink(t0=0.0)
    with pytest.raises(probe.ProbeError) as excinfo:
        sink.emit(_event("message_delta", text="leak: reasoning.encrypted_content"))
    assert excinfo.value.category == "public_stream_leak"
    with pytest.raises(probe.ProbeError):
        sink.emit(_event("stage", stage="x", detail="Authorization: Bearer abc"))


def test_evidence_sink_records_redacted_counts_only():
    sink = probe.EvidenceSink(t0=0.0)
    sink.emit(_event("message_delta", text="公开增量"))
    sink.emit(_event("tool_started", tool="read_file", detail="/materials/x.md"))
    sink.emit(_event("tool_finished", tool="read_file", detail="ok"))
    summary = sink.summary(total_ms=10)
    assert summary["events_by_kind"]["message_delta"] == 1
    assert summary["public_text_chars"] == 4
    assert summary["tool_events"] == ["read_file:started", "read_file:finished"]
    # Text bodies are never stored — only counts and whitelisted names.
    assert "公开增量" not in json.dumps(summary, ensure_ascii=False)


def test_secret_values_never_pass_the_evidence_gate():
    blob = json.dumps({"leak": probe._secret_values()[0] or "x"})
    if probe._secret_values():
        assert probe._evidence_secret_violation(blob) == "configured_secret_value"
    assert probe._evidence_secret_violation('{"safe": 1}') is None


# ---------------------------------------------------------------------------
# Candidate model construction: Responses-native, effort preserved
# ---------------------------------------------------------------------------

def _settings(**overrides):
    from app.lib.settings import Settings

    return Settings(_env_file=None, **{
        "ai_provider": "openai",
        "ai_model": "gpt-5.6-luna",
        "ai_api_key": "test-provider-key",
        "ai_base_url": "https://provider.example/v1",
        "ai_reasoning_effort": "medium",
        **overrides,
    })


def test_probe_runtime_is_production_assembly_with_target_gate():
    from app.lib.ai_runtime.deep_runtime import RuntimeBudget

    model, identity, contract, summary = probe.build_probe_runtime(
        RuntimeBudget(), _settings()
    )
    try:
        # The model comes from the PRODUCTION factory: native Responses,
        # effort preserved, client-held encrypted history.
        assert model.use_responses_api is True
        assert model.reasoning == {"effort": "medium"}
        assert model.store is False
        assert model.include == ["reasoning.encrypted_content"]
        assert model.use_previous_response_id is False
        # No Chat-only _generate override anywhere in the production path.
        assert "_generate" not in type(model).__dict__
        assert contract.protocol == "responses"
        assert contract.reasoning_effort == "medium"
        assert summary["protocol"] == "responses"
        assert summary["endpoint_fingerprint"] == identity.endpoint_fingerprint
        assert summary["contract_fingerprint"] == contract.fingerprint
        assert "provider.example" not in json.dumps(summary)

        from langchain_core.messages import HumanMessage

        payload = model._get_request_payload([HumanMessage(content="hi")], stop=None)
        assert payload["reasoning"] == {"effort": "medium"}
        assert payload["store"] is False
        assert payload["include"] == ["reasoning.encrypted_content"]
    finally:
        model.http_client.close()


def test_probe_runtime_refuses_non_openai_provider():
    from app.lib.ai_runtime.deep_runtime import RuntimeBudget

    with pytest.raises(probe.ProbeError) as excinfo:
        probe.build_probe_runtime(RuntimeBudget(), _settings(
            ai_provider="anthropic", ai_model="claude-sonnet-4-6",
            ai_reasoning_effort="",
        ))
    assert excinfo.value.category == "provider_unsupported"


def test_probe_runtime_refuses_non_responses_protocol():
    from app.lib.ai_runtime.deep_runtime import RuntimeBudget

    with pytest.raises(probe.ProbeError) as excinfo:
        probe.build_probe_runtime(RuntimeBudget(), _settings(
            ai_openai_api="chat_completions",
        ))
    assert excinfo.value.category == "protocol_not_target"


def test_probe_runtime_refuses_empty_effort():
    from app.lib.ai_runtime.deep_runtime import RuntimeBudget

    with pytest.raises(probe.ProbeError) as excinfo:
        probe.build_probe_runtime(RuntimeBudget(), _settings(ai_reasoning_effort=""))
    assert excinfo.value.category == "effort_missing"


def test_probe_runtime_requires_full_settings_snapshot():
    from app.lib.ai_runtime.deep_runtime import RuntimeBudget

    with pytest.raises(probe.ProbeError) as excinfo:
        probe.build_probe_runtime(RuntimeBudget(), SimpleNamespace(ai_provider="openai"))
    assert excinfo.value.category == "config_invalid"


# ---------------------------------------------------------------------------
# L01 request-shape assertions and request summary redaction
# ---------------------------------------------------------------------------

def _good_summary(**overrides):
    base = {
        "path": "/v1/responses",
        "stream": True,
        "reasoning_effort": "medium",
        "store": False,
        "include": ["reasoning.encrypted_content"],
        "previous_response_id": None,
        "tool_count": 7,
        "tool_names": ["delete", "edit_file", "glob", "grep", "ls", "read_file", "write_file"],
        "tool_choice": None,
        "text_format_type": "json_schema",
        "input_kinds": ["message"],
    }
    base.update(overrides)
    return base


def _l01(monkeypatch, summaries):
    monkeypatch.setattr(probe, "_expected_effort", lambda: "medium")
    sink = probe.EvidenceSink(t0=0.0)
    sink.request_summaries.extend(summaries)
    sink.kind_counts.update({"tool_finished": 1, "message_delta": 2})
    sink.first_delta_ms, sink.last_delta_ms, sink.first_tool_ms = 10, 90, 50
    config = SimpleNamespace()
    probe._assert_l01(config, sink.summary(total_ms=100), sink)


def test_l01_accepts_responses_combination(monkeypatch):
    _l01(monkeypatch, [_good_summary()])


@pytest.mark.parametrize("override,category", [
    ({"path": "/v1/chat/completions"}, "protocol_mismatch"),
    ({"reasoning_effort": "none"}, "effort_mismatch"),
    ({"reasoning_effort": None}, "effort_mismatch"),
    ({"store": True}, "history_policy_mismatch"),
    ({"include": None}, "history_policy_mismatch"),
    ({"previous_response_id": "resp_123"}, "server_session_dependency"),
    ({"text_format_type": "text"}, "schema_strategy_mismatch"),
    ({"tool_names": ["ls", "grep"]}, "tools_missing"),
    ({"tool_names": ["read_file", "execute", "task"]}, "restricted_tools_leaked"),
])
def test_l01_rejects_degraded_combinations(monkeypatch, override, category):
    with pytest.raises(probe.ProbeError) as excinfo:
        _l01(monkeypatch, [_good_summary(**override)])
    assert excinfo.value.category == category


def test_l01_rejects_missing_stream_or_tool_evidence(monkeypatch):
    monkeypatch.setattr(probe, "_expected_effort", lambda: "medium")
    sink = probe.EvidenceSink(t0=0.0)
    sink.request_summaries.append(_good_summary())
    config = SimpleNamespace()
    with pytest.raises(probe.ProbeError) as excinfo:
        probe._assert_l01(config, sink.summary(total_ms=1), sink)
    assert excinfo.value.category == "no_tool_round_trip"


def test_request_summary_is_redacted_and_structural():
    body = json.dumps({
        "model": "gpt-5.6-luna",
        "stream": True,
        "reasoning": {"effort": "medium"},
        "store": False,
        "include": ["reasoning.encrypted_content"],
        "input": [
            {"type": "message", "role": "user", "content": "材料正文哨兵"},
            {"type": "function_call", "name": "read_file", "call_id": "c1"},
            {"type": "function_call_output", "call_id": "c1", "output": "工具正文哨兵"},
        ],
        "tools": [{"type": "function", "name": "read_file"}],
        "text": {"format": {"type": "json_schema", "schema": {"x": 1}}},
    }, ensure_ascii=False).encode()
    request = SimpleNamespace(
        url=SimpleNamespace(path="/v1/responses"),
        content=body,
        headers={"authorization": "Bearer secret-token"},
    )
    summary = probe._request_summary(request)
    blob = json.dumps(summary, ensure_ascii=False)
    assert summary["path"] == "/v1/responses"
    assert summary["text_format_type"] == "json_schema"
    assert summary["input_kinds"] == ["function_call", "function_call_output", "message"]
    # No raw bodies, headers or credentials in the summary.
    for forbidden in ("材料正文哨兵", "工具正文哨兵", "secret-token", "Bearer"):
        assert forbidden not in blob


def test_error_category_is_whitelisted():
    class ModelInvalidRequestError(Exception):
        pass

    class APIStatusError(Exception):
        def __init__(self, status_code: int) -> None:
            super().__init__("boom")
            self.response = SimpleNamespace(status_code=status_code)

    assert probe._error_category(ModelInvalidRequestError()) == "model_invalid_request"
    assert probe._error_category(RuntimeError()) == "unknown"
    assert probe._error_category(APIStatusError(400)) == "http_400"

    from app.lib.ai_runtime.adapters import RubricGenerationFailure
    from app.lib.ai_runtime.deep_runtime import BudgetExceededError

    assert (
        probe._error_category(RubricGenerationFailure("AI_CALL_FAILED", "x"))
        == "generation_failure:AI_CALL_FAILED"
    )
    assert probe._error_category(BudgetExceededError("x")) == "budget_exceeded"


# ---------------------------------------------------------------------------
# Bounded stage re-attempts: transient only, contract violations never retried
# ---------------------------------------------------------------------------

def test_bounded_stage_retries_transient_then_succeeds():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise probe.ProbeError(
                "resume", "generation_failure:AI_CALL_FAILED", "transient"
            )
        return {"ok": True}

    payload, attempts = probe._run_stage_bounded("resume", flaky, max_attempts=3)
    assert payload == {"ok": True}
    assert attempts == 3


def test_bounded_stage_never_retries_contract_violations():
    def violating():
        raise probe.ProbeError("resume", "not_resumed", "contract violation")

    with pytest.raises(probe.ProbeError) as excinfo:
        probe._run_stage_bounded("resume", violating, max_attempts=3)
    assert excinfo.value.category == "not_resumed"


def test_bounded_stage_respects_attempt_ceiling():
    calls = []

    def always_transient():
        calls.append(1)
        raise probe.ProbeError("resume", "http_429", "rate limited")

    with pytest.raises(probe.ProbeError) as excinfo:
        probe._run_stage_bounded("resume", always_transient, max_attempts=2)
    assert excinfo.value.category == "http_429"
    assert len(calls) == 2


def test_transient_category_classification():
    assert probe._is_transient("generation_failure:AI_CALL_FAILED")
    assert probe._is_transient("http_429")
    assert probe._is_transient("timeout")
    assert not probe._is_transient("generation_failure:AI_RUN_INTERRUPTED")
    assert not probe._is_transient("budget_exceeded")
    assert not probe._is_transient("http_400")
    assert not probe._is_transient("protocol_mismatch")
    assert not probe._is_transient("duplicate_initial_input")


def test_stage_child_args_keep_contract_identical(tmp_path):
    args = _parse([
        "--execute",
        "--checkpoint-dsn", "postgresql://u@h:5432/blue_benchmark_c1_capability",
        "--corpus-root", str(tmp_path),
        "--out", str(tmp_path / "out"),
        "--max-model-calls", "9",
        "--max-tool-calls", "33",
        "--max-seconds", "77",
    ])
    config = probe.resolve_config(args)
    child_args = probe._stage_child_args(config, "run-child")
    assert "--stage" in child_args and "run-child" in child_args
    # The interrupted run and the orchestrator share ONE budget contract.
    assert child_args[child_args.index("--max-model-calls") + 1] == "9"
    assert child_args[child_args.index("--max-tool-calls") + 1] == "33"
    assert child_args[child_args.index("--max-seconds") + 1] == "77.0"
    assert child_args[child_args.index("--checkpoint-dsn") + 1] == config.checkpoint_dsn


# ---------------------------------------------------------------------------
# Orchestrator wiring: full sequence with stubbed stages (offline)
# ---------------------------------------------------------------------------

def _stub_orchestrator(monkeypatch, tmp_path, *, resume_failures=0, full_run_failures=0):
    args = _parse([
        "--execute",
        "--checkpoint-dsn", "postgresql://u@127.0.0.1:5432/blue_benchmark_c1_capability",
        "--corpus-root", str(tmp_path),
        "--out", str(tmp_path / "out"),
    ])
    config = probe.resolve_config(args)
    calls: list[str] = []
    state = {"resume_failures": resume_failures, "full_run_failures": full_run_failures}

    def stub(name, payload=None, fail_key=None):
        def _fn(_config):
            calls.append(name)
            if fail_key and state[fail_key] > 0:
                state[fail_key] -= 1
                raise probe.ProbeError(
                    name, "generation_failure:AI_CALL_FAILED", "transient"
                )
            return payload if payload is not None else {"stub": name}
        return _fn

    monkeypatch.setattr(probe, "verify_live_database", lambda cfg: cfg.db_name)
    monkeypatch.setattr(probe, "stage_cleanup", stub("cleanup"))
    monkeypatch.setattr(
        probe, "stage_full_run", stub("full_run", fail_key="full_run_failures")
    )
    monkeypatch.setattr(
        probe, "stage_resume", stub("resume", fail_key="resume_failures")
    )
    monkeypatch.setattr(probe, "stage_reread", stub("reread"))
    monkeypatch.setattr(probe, "_spawn_stage",
                        lambda cfg, stage, expect_code=0: calls.append(f"spawn:{stage}"))
    monkeypatch.setattr(probe, "_evidence_base", lambda cfg: {"stub_base": True})
    return config, calls


def test_run_execute_orchestrates_full_sequence(monkeypatch, tmp_path):
    config, calls = _stub_orchestrator(monkeypatch, tmp_path)
    assert probe.run_execute(config) == 0
    assert calls == [
        "cleanup",            # pre-clean
        "full_run",
        "cleanup",            # post full-run clean
        "spawn:run-child",    # interrupted subprocess
        "resume",
        "reread",
        "cleanup",            # final zero-residue cleanup
    ]
    evidence = json.loads(
        (tmp_path / "out" / "c1-capability-evidence.json").read_text(encoding="utf-8")
    )
    assert evidence["verdict"] == "PASS"
    assert evidence["full_run_attempts"] == 1
    assert evidence["resume_attempts"] == 1
    assert evidence["interrupt"] == {"child_exit_code": probe.INTERRUPT_EXIT_CODE}


def test_run_execute_retries_transient_resume_on_same_thread(monkeypatch, tmp_path):
    config, calls = _stub_orchestrator(monkeypatch, tmp_path, resume_failures=2)
    assert probe.run_execute(config) == 0
    # Two transient failures, then success — bounded, no extra interrupt spawn
    # and no thread cleaning between resume attempts (continuation semantics).
    assert calls.count("resume") == 3
    assert calls.count("spawn:run-child") == 1
    assert calls.count("cleanup") == 3
    evidence = json.loads(
        (tmp_path / "out" / "c1-capability-evidence.json").read_text(encoding="utf-8")
    )
    assert evidence["resume_attempts"] == 3
    assert evidence["verdict"] == "PASS"


def test_run_execute_cleans_thread_between_full_run_attempts(monkeypatch, tmp_path):
    config, calls = _stub_orchestrator(monkeypatch, tmp_path, full_run_failures=1)
    assert probe.run_execute(config) == 0
    # pre-clean, failed full_run, between-attempt clean, successful full_run,
    # post-full-run clean, ..., final clean
    assert calls[:4] == ["cleanup", "full_run", "cleanup", "full_run"]
    evidence = json.loads(
        (tmp_path / "out" / "c1-capability-evidence.json").read_text(encoding="utf-8")
    )
    assert evidence["full_run_attempts"] == 2


def test_run_execute_writes_fail_evidence_on_exhausted_attempts(monkeypatch, tmp_path):
    config, _calls = _stub_orchestrator(monkeypatch, tmp_path, resume_failures=99)
    with pytest.raises(SystemExit) as excinfo:
        probe.run_execute(config)
    assert excinfo.value.code == 1
    evidence = json.loads(
        (tmp_path / "out" / "c1-capability-evidence.json").read_text(encoding="utf-8")
    )
    assert evidence["verdict"] == "FAIL:resume:generation_failure:AI_CALL_FAILED"
