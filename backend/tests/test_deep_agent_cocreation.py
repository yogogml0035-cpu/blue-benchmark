from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
import app.lib.ai_runtime.adapters as adapters

from app.features.auth import repository as auth_repository
from app.features.case_builder import cocreation_repository, cocreation_service
from app.features.case_builder import ingestion_repository
from app.features.workspaces import repository as workspace_repository
from app.lib.ai_runtime import get_adapters, reset_adapters, set_adapters
from app.lib.ai_runtime.adapters import (
    FakeCoverageReviewer,
    FakeEvidenceAnalyzer,
    FakeStandardCoCreator,
    AgentRunResult,
    RuntimeAdapters,
    DeepAgentsCoverageReviewer,
    DeepAgentsEvidenceAnalyzer,
    DeepAgentsStandardCoCreator,
    _bounded_evidence_context,
    _normalize_evidence_refs,
    _assert_batch_output_scope,
    _allow_teacher_interrupt,
    _checkpoint_id_from_state,
    _completion_evidence_refs,
    _ensure_completion_source_scope_refs,
    _normalize_nested_evidence_refs,
    _prune_completion_fields,
)
from app.lib.ai_runtime.context import AgentRunContext
from app.lib.ai_runtime.profile import get_ai_profile
from app.lib.ai_runtime.evidence import EvidenceDocument, ReadOnlyEvidenceBackend
from app.lib.ai_runtime.evidence import EvidenceValidationError, validate_evidence_refs
from app.features.case_builder.cocreation_schemas import AgentEvidenceRef, BatchAnalysis, CoCreationAgentResult, CoCreationKind, CoverageReview, EventLocator, JsonPointerLocator
from app.lib.ai_runtime.middleware import ModelToolSurfaceMiddleware
from app.lib.ai_runtime.adapters import _question_from_interrupt
from langchain.agents.middleware.types import ToolCallRequest
from app.lib.database import clear_business_data
from app.lib.operations import attempts as attempt_repository
from app.lib.operations import repository as operation_repository
from app.lib.operations.worker import SupersededOperation, default_worker
from app.lib.storage import LocalStorage
from app.main import app
from langchain_openai import ChatOpenAI


@pytest.fixture(autouse=True)
def reset_state():
    clear_business_data()
    reset_adapters()
    yield
    reset_adapters()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _setup(client: TestClient) -> str:
    suffix = uuid4().hex[:8]
    response = client.post(
        "/api/auth/register",
        json={
            "username": f"cocreation-{suffix}",
            "email": f"cocreation-{suffix}@example.com",
            "password": "password123",
        },
    )
    assert response.status_code == 201
    response = client.post("/api/workspaces", json={"name": "共创场景"})
    assert response.status_code == 201
    return response.json()["workspace"]["id"]


def _confirmed_package(client: TestClient) -> tuple[str, str, int]:
    workspace_id = _setup(client)
    upload = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches",
        data={"title": "真实任务包"},
        files=[
            ("files", ("brief.md", BytesIO(b"brief\n"), "text/markdown")),
            ("files", ("events.jsonl", BytesIO(b'{"event": 1}\n'), "application/x-ndjson")),
        ],
    )
    assert upload.status_code == 202
    batch_id = upload.json()["batch"]["id"]
    assert default_worker().run_once().status.value == "succeeded"
    proposals = client.get(f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}/task-packages")
    assert proposals.status_code == 200
    file_ids = [file_id for file_id in proposals.json()["task_packages"][0]["evidence_file_ids"]]
    batch_revision = proposals.json()["batch_revision"]
    for file_id in file_ids:
        disposition = client.patch(
            f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}/files/{file_id}/disposition",
            json={"role": "runtime", "visibility": "runtime", "required": True, "batch_revision": batch_revision},
        )
        assert disposition.status_code == 200
        batch_revision += 1
    confirmed = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}/task-groups/confirmation",
        json={
            "command_id": "group-confirm-1",
            "batch_revision": batch_revision,
            "groups": [
                {
                    "proposal_key": "teacher-group",
                    "title": "老师确认的任务",
                    "summary": "同一真实任务的多份证据",
                    "evidence_file_ids": file_ids,
                }
            ],
        },
    )
    assert confirmed.status_code == 200
    package = confirmed.json()["task_packages"][0]
    return workspace_id, package["id"], package["revision"]


def test_read_only_backend_is_scoped_and_reads_to_eof(tmp_path: Path):
    storage = LocalStorage(tmp_path)
    content = "\n".join(f"line-{index}" for index in range(1, 131))
    stored = storage.stage_bytes("batch", "file", content.encode())
    storage.publish(stored.key, "evidence/batch/file")
    document = EvidenceDocument(
        file_id="file",
        name="tail.md",
        storage_key="evidence/batch/file",
        size_bytes=len(content),
        sha256=stored.sha256,
        parse_state="parsed",
        canonical_view={"kind": "text", "line_count": 130},
        role="runtime",
        ignored=False,
        visibility="runtime",
    )
    backend = ReadOnlyEvidenceBackend({"file": document}, storage)

    first = backend.read("/evidence/file", offset=0, limit=100)
    tail = backend.read("/evidence/file", offset=100, limit=100)
    manifest = backend.read("/evidence/manifest.json")
    assert "file" in (manifest.file_data or {})["content"]
    assert "storage_key" not in (manifest.file_data or {})["content"]
    assert first.total_lines == 130
    assert first.next_offset == 100
    assert "line-100" in (first.file_data or {})["content"]
    assert tail.next_offset is None
    assert "line-130" in (tail.file_data or {})["content"]
    assert backend.read("/evidence/file", limit=0).no_lines_requested
    assert backend.read("/etc/passwd").error
    assert backend.write("/evidence/file", "overwrite").error
    assert backend.edit("/evidence/file", "line-1", "changed").error
    assert backend.delete("/evidence/file").error
    assert backend.grep("line-130", path="/evidence").matches[0]["line"] == 130


def test_evidence_context_capsule_keeps_head_and_tail_without_sending_full_file(tmp_path: Path):
    storage = LocalStorage(tmp_path)
    content = "\n".join(["head-marker", *[f"middle-{index}" for index in range(1, 2_000)], "tail-marker"])
    stored = storage.stage_bytes("batch", "file", content.encode())
    storage.publish(stored.key, "evidence/batch/file")
    document = EvidenceDocument(
        file_id="file",
        name="long.md",
        storage_key="evidence/batch/file",
        size_bytes=len(content),
        sha256=stored.sha256,
        parse_state="parsed",
        canonical_view={"kind": "text", "line_count": 2_001},
        role="runtime",
        ignored=False,
        visibility="runtime",
    )

    capsule = _bounded_evidence_context({"file": document}, storage)

    assert len(capsule) < 5_000
    assert "head-marker" in capsule
    assert "tail-marker" in capsule
    assert "middle-1000" not in capsule


def test_evidence_ref_keeps_verified_locator_but_drops_noncanonical_quote(tmp_path: Path):
    storage = LocalStorage(tmp_path)
    content = "line one\nline two\n"
    stored = storage.stage_bytes("batch", "file", content.encode())
    storage.publish(stored.key, "evidence/batch/file")
    document = EvidenceDocument(
        file_id="file",
        name="evidence.md",
        storage_key="evidence/batch/file",
        size_bytes=len(content),
        sha256=stored.sha256,
        parse_state="parsed",
        canonical_view={"kind": "text", "line_count": 2},
        role="runtime",
        ignored=False,
        visibility="runtime",
    )
    ref = AgentEvidenceRef(
        source_id="file",
        locator={"kind": "line_range", "start_line": 1, "end_line": 1},
        quote="model-normalized quote",
    )

    normalized = _normalize_evidence_refs([ref], {"file": document}, storage)

    assert normalized[0].locator is not None
    assert normalized[0].quote is None


def test_evidence_ref_drops_quote_when_only_source_id_is_verifiable(tmp_path: Path):
    storage = LocalStorage(tmp_path)
    content = "line one\nline two\n"
    stored = storage.stage_bytes("batch", "file", content.encode())
    storage.publish(stored.key, "evidence/batch/file")
    document = EvidenceDocument(
        file_id="file",
        name="evidence.md",
        storage_key="evidence/batch/file",
        size_bytes=len(content),
        sha256=stored.sha256,
        parse_state="parsed",
        canonical_view={"kind": "text", "line_count": 2},
        role="runtime",
        ignored=False,
        visibility="runtime",
    )
    ref = AgentEvidenceRef(source_id="file", quote="model-normalized quote")

    normalized = _normalize_evidence_refs([ref], {"file": document}, storage)

    assert normalized[0].locator is None
    assert normalized[0].quote is None


def test_completion_result_keeps_model_refs_for_validation():
    document = EvidenceDocument(
        file_id="file",
        name="evidence.md",
        storage_key="evidence/file",
        size_bytes=0,
        sha256="0" * 64,
        parse_state="parsed",
        canonical_view={"kind": "text", "line_count": 0},
        role="runtime",
        ignored=False,
        visibility="runtime",
    )
    raw = {
        "phase": "complete",
        "contract": {
            "task_boundary": "boundary",
            "evidence_refs": [{"source_id": "model-invented"}],
        },
    }

    result = _completion_evidence_refs(raw, {"file": document})

    assert result["contract"]["evidence_refs"] == [{"source_id": "model-invented"}]


def test_completion_result_does_not_invent_missing_nested_refs():
    document = EvidenceDocument(
        file_id="file",
        name="evidence.md",
        storage_key="evidence/file",
        size_bytes=0,
        sha256="0" * 64,
        parse_state="parsed",
        canonical_view={"kind": "text", "line_count": 0},
        role="runtime",
        ignored=False,
        visibility="runtime",
    )

    result = _completion_evidence_refs(
        {"phase": "complete", "judgment_package": {"minimum_quality_line": "usable"}},
        {"file": document},
    )

    assert "evidence_refs" not in result["judgment_package"]


def test_completion_result_maps_file_id_to_source_id_before_validation():
    result = _completion_evidence_refs(
        {"evidence_refs": [{"source_id": "file", "file_id": None}]},
        {},
    )

    assert result["evidence_refs"] == [{"source_id": "file"}]


def test_completion_result_adds_only_confirmed_runtime_scope_refs_when_omitted():
    runtime = EvidenceDocument(
        file_id="runtime",
        name="runtime.md",
        storage_key="evidence/runtime",
        size_bytes=0,
        sha256="0" * 64,
        parse_state="parsed",
        canonical_view={"kind": "text", "line_count": 0},
        role="runtime",
        ignored=False,
        visibility="runtime",
    )
    provenance = EvidenceDocument(
        file_id="provenance",
        name="trace.md",
        storage_key="evidence/provenance",
        size_bytes=0,
        sha256="0" * 64,
        parse_state="parsed",
        canonical_view={"kind": "text", "line_count": 0},
        role="provenance",
        ignored=False,
        visibility="provenance",
    )

    result = _ensure_completion_source_scope_refs(
        {"contract": {"task_boundary": "boundary"}},
        {"runtime": runtime, "provenance": provenance},
    )

    assert result["contract"]["evidence_refs"] == [{"source_id": "runtime"}]


def test_completion_result_prunes_model_only_fields():
    raw = {
        "phase": "complete",
        "delta": {"added": ["x"], "status": "completed"},
        "blocking_gaps": [{"id": "gap-1", "text": "需要老师确认", "extra": True}],
    }

    result = _prune_completion_fields(raw)

    assert result["delta"] == {"added": ["x"]}
    assert result["blocking_gaps"] == [{"id": "gap-1", "text": "需要老师确认"}]


def test_virtual_evidence_paths_are_canonicalized_only_for_known_files():
    storage = LocalStorage()
    stored = storage.stage_bytes("batch", "file", b"evidence")
    storage.publish(stored.key, "evidence/batch/file")
    document = EvidenceDocument(
        file_id="file",
        name="evidence.md",
        storage_key="evidence/batch/file",
        size_bytes=len(b"evidence"),
        sha256=stored.sha256,
        parse_state="parsed",
        canonical_view={"kind": "text", "line_count": 1},
        role="runtime",
        ignored=False,
        visibility="runtime",
    )
    result = BatchAnalysis(
        groups=[
            {
                "proposal_key": "group-1",
                "title": "任务",
                "summary": "摘要",
                "evidence_file_ids": ["/evidence/file"],
                "attempts": [
                    {
                        "attempt_key": "attempt-1",
                        "label": "尝试",
                        "evidence_file_ids": ["/evidence/file"],
                    }
                ],
                "evidence_refs": [{"source_id": "/evidence/file"}],
            }
        ],
        file_roles={"/evidence/file": "runtime"},
    )

    normalized = _normalize_nested_evidence_refs(result, {"file": document}, storage)

    group = normalized.groups[0]
    assert group.evidence_file_ids == ["file"]
    assert group.attempts[0].evidence_file_ids == ["file"]
    assert group.evidence_refs[0].source_id == "file"
    assert normalized.file_roles == {"file": "runtime"}


def test_unknown_virtual_evidence_path_stays_out_of_scope():
    document = EvidenceDocument(
        file_id="file",
        name="evidence.md",
        storage_key="evidence/file",
        size_bytes=0,
        sha256="0" * 64,
        parse_state="parsed",
        canonical_view={"kind": "text", "line_count": 0},
        role="runtime",
        ignored=False,
        visibility="runtime",
    )
    result = BatchAnalysis(
        groups=[],
        unassigned_file_ids=["/evidence/unknown"],
        file_roles={"/evidence/unknown": "runtime"},
    )

    normalized = _normalize_nested_evidence_refs(result, {"file": document})

    assert normalized.unassigned_file_ids == ["/evidence/unknown"]
    assert set(normalized.file_roles) == {"/evidence/unknown"}


def test_batch_output_scope_checks_all_file_reference_fields():
    document = EvidenceDocument(
        file_id="file",
        name="evidence.md",
        storage_key="evidence/file",
        size_bytes=0,
        sha256="0" * 64,
        parse_state="parsed",
        canonical_view={"kind": "text", "line_count": 0},
        role="runtime",
        ignored=False,
        visibility="runtime",
    )

    with pytest.raises(EvidenceValidationError, match="out-of-scope"):
        _assert_batch_output_scope(
            BatchAnalysis(unassigned_file_ids=["unknown"], file_roles={"file": "runtime"}),
            {"file": document},
        )


def test_batch_output_scope_rejects_cross_group_evidence_references():
    first = EvidenceDocument(
        file_id="first",
        name="first.md",
        storage_key="evidence/first",
        size_bytes=0,
        sha256="0" * 64,
        parse_state="parsed",
        canonical_view={"kind": "text", "line_count": 0},
        role="runtime",
        ignored=False,
        visibility="runtime",
    )
    second = EvidenceDocument(
        file_id="second",
        name="second.md",
        storage_key="evidence/second",
        size_bytes=0,
        sha256="0" * 64,
        parse_state="parsed",
        canonical_view={"kind": "text", "line_count": 0},
        role="runtime",
        ignored=False,
        visibility="runtime",
    )

    with pytest.raises(EvidenceValidationError, match="cross-group"):
        _assert_batch_output_scope(
            BatchAnalysis(
                groups=[
                    {
                        "proposal_key": "group-1",
                        "title": "第一组",
                        "summary": "摘要",
                        "evidence_file_ids": ["first"],
                        "evidence_refs": [{"source_id": "second"}],
                    }
                ]
            ),
            {"first": first, "second": second},
        )


def test_batch_analyzer_retries_once_after_scope_violation(monkeypatch: pytest.MonkeyPatch):
    profile = get_ai_profile()
    context = AgentRunContext(
        user_id="u",
        workspace_id="w",
        target_type="upload_batch",
        target_id="batch",
        thread_key="batch-repair",
        business_revision=0,
        evidence_file_ids=("file",),
        evidence_scope="/evidence/batch",
        ai_profile_version=profile.version,
        graph_schema_version="m0-cocreation-graph-v2",
    )
    document = EvidenceDocument(
        file_id="file",
        name="evidence.md",
        storage_key="evidence/file",
        size_bytes=0,
        sha256="0" * 64,
        parse_state="parsed",
        canonical_view={"kind": "text", "line_count": 0},
        role="runtime",
        ignored=False,
        visibility="runtime",
    )
    outputs = iter(
        [
            AgentRunResult(BatchAnalysis(unassigned_file_ids=["unknown"])),
            AgentRunResult(BatchAnalysis(unassigned_file_ids=["file"])),
        ]
    )
    analyzer = DeepAgentsEvidenceAnalyzer(
        model=ChatOpenAI(model="test-model", api_key="test-secret", base_url="https://models.example/v1", streaming=False),
        model_spec="openai:test-model",
    )
    calls = 0

    monkeypatch.setattr("app.lib.ai_runtime.adapters._bounded_evidence_context", lambda _documents: "{}")
    monkeypatch.setattr(analyzer, "_graph", lambda *_args, **_kwargs: object())

    def invoke(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return next(outputs)

    monkeypatch.setattr(analyzer, "_invoke", invoke)

    result = analyzer.analyze(context, {"file": document})

    assert calls == 2
    assert result.result.unassigned_file_ids == ["file"]


def test_filesystem_permissions_allow_evidence_directory_but_not_host_root():
    from deepagents.middleware.filesystem import _check_fs_permission

    rules = DeepAgentsEvidenceAnalyzer._permissions(["file"])

    assert _check_fs_permission(rules, "read", "/evidence") == "allow"
    assert _check_fs_permission(rules, "read", "/evidence/file") == "allow"
    assert _check_fs_permission(rules, "read", "/etc/passwd") == "deny"
    assert _check_fs_permission(rules, "write", "/evidence/file") == "deny"


def test_checkpoint_id_reader_accepts_a_returned_config():
    assert _checkpoint_id_from_state({"configurable": {"checkpoint_id": "next"}}) == "next"


def test_model_tool_surface_and_hitl_envelope_fail_closed():
    middleware = ModelToolSurfaceMiddleware({"read_file", "ask_teacher"})
    hidden = middleware.wrap_tool_call(
        ToolCallRequest(
            tool_call={"type": "tool_call", "name": "execute", "args": {}, "id": "hidden"},
            tool=None,
            state={},
            runtime=None,
        ),
        lambda _: pytest.fail("hidden tool must not reach the handler"),
    )
    assert hidden.status == "error"
    with pytest.raises(RuntimeError, match="exactly one"):
        _question_from_interrupt(
            {
                "action_requests": [
                    {"name": "ask_teacher", "args": {}, "description": "one"},
                    {"name": "ask_teacher", "args": {}, "description": "two"},
                ],
                "review_configs": [
                    {"action_name": "ask_teacher", "allowed_decisions": ["respond"]},
                    {"action_name": "ask_teacher", "allowed_decisions": ["respond"]},
                ],
            }
        )


def test_ask_teacher_args_map_to_business_question_contract():
    question = _question_from_interrupt(
        {
            "action_requests": [
                {
                    "name": "ask_teacher",
                    "args": {
                        "question_id": "question-1",
                        "question": "需要确认什么？",
                        "reason": "补齐边界。",
                        "gap_type": "scope",
                    },
                }
            ],
            "review_configs": [
                {"action_name": "ask_teacher", "allowed_decisions": ["respond"]}
            ],
        }
    )

    assert question.id == "question-1"
    assert question.text == "需要确认什么？"


def test_cocreation_resume_uses_hitl_message_field(monkeypatch: pytest.MonkeyPatch):
    from langgraph.types import Command

    class CapturingGraph:
        def invoke(self, payload, **_kwargs):
            assert isinstance(payload, Command)
            assert payload.resume == {"decisions": [{"type": "respond", "message": "老师回答"}]}
            return {"messages": [], "structured_response": CoCreationAgentResult(phase="complete").model_dump(mode="json")}

        def get_state(self, _config):
            return None

    profile = get_ai_profile()
    context = AgentRunContext(
        user_id="u",
        workspace_id="w",
        target_type="task",
        target_id="t",
        thread_key="resume-message-field",
        business_revision=1,
        evidence_file_ids=(),
        evidence_scope="/evidence/task",
        ai_profile_version=profile.version,
        graph_schema_version="m0-cocreation-graph-v2",
    )
    creator = DeepAgentsStandardCoCreator(
        checkpointer=object(),
        model=ChatOpenAI(model="test-model", api_key="test-secret", base_url="https://models.example/v1", streaming=False),
        model_spec="openai:test-model",
    )
    monkeypatch.setattr(creator, "_graph", lambda *_args, **_kwargs: CapturingGraph())

    result = creator.resume(context, CoCreationKind.scenario_contract, "accepted", "老师回答")

    assert result.result.phase == "complete"


def test_cocreation_resume_adds_completion_guard_at_question_budget(monkeypatch: pytest.MonkeyPatch):
    class StructuredModel:
        def invoke(self, _payload):
            return CoCreationAgentResult(
                phase="complete",
                contract=None,
                judgment_package=None,
            )

    class CapturingModel:
        def with_structured_output(self, *_args, **_kwargs):
            return StructuredModel()

    profile = get_ai_profile()
    context = AgentRunContext(
        user_id="u",
        workspace_id="w",
        target_type="task",
        target_id="t",
        thread_key="resume-budget-guard",
        business_revision=12,
        co_creation_question_count=12,
        evidence_file_ids=(),
        evidence_scope="/evidence/task",
        ai_profile_version=profile.version,
        graph_schema_version="m0-cocreation-graph-v2",
    )
    creator = DeepAgentsStandardCoCreator(
        checkpointer=object(),
        model=ChatOpenAI(model="test-model", api_key="test-secret", base_url="https://models.example/v1", streaming=False),
        model_spec="openai:test-model",
    )
    monkeypatch.setattr(creator, "_model", lambda: CapturingModel())
    monkeypatch.setattr(creator, "_persist_completion_checkpoint", lambda *_args: "produced")

    with pytest.raises(ValueError, match="runtime evidence scope"):
        creator.resume(context, CoCreationKind.scenario_contract, "accepted", "老师回答")



def test_teacher_interrupt_is_auto_accepted_at_question_budget():
    from types import SimpleNamespace

    below_budget = SimpleNamespace(runtime=SimpleNamespace(context=SimpleNamespace(co_creation_question_count=11)))
    at_budget = SimpleNamespace(runtime=SimpleNamespace(context=SimpleNamespace(co_creation_question_count=12)))

    assert _allow_teacher_interrupt(below_budget) is True
    assert _allow_teacher_interrupt(at_budget) is False


def test_auto_accepted_teacher_tool_returns_completion_signal():
    assert "QUESTION_BUDGET_EXHAUSTED" in adapters.ask_teacher.invoke(
        {
            "question_id": "q",
            "question": "q",
            "reason": "r",
            "gap_type": "scope",
            "evidence_refs": [],
        }
    )


def test_json_and_event_locators_are_checked_against_content(tmp_path: Path):
    storage = LocalStorage(tmp_path)
    json_bytes = b'{"facts":{"id":"fact-1"}}'
    stored = storage.stage_bytes("batch", "json", json_bytes)
    storage.publish(stored.key, "evidence/batch/json")
    document = EvidenceDocument(
        file_id="json",
        name="events.jsonl",
        storage_key="evidence/batch/json",
        size_bytes=len(json_bytes),
        sha256=stored.sha256,
        parse_state="parsed",
        canonical_view={"kind": "json", "line_count": 1},
        role="runtime",
        ignored=False,
        visibility="runtime",
    )
    valid = AgentEvidenceRef(source_id="json", locator=JsonPointerLocator(pointer="/facts/id"))
    validate_evidence_refs([valid], {"json": document}, storage)
    invalid = AgentEvidenceRef(source_id="json", locator=JsonPointerLocator(pointer="/facts/missing"))
    with pytest.raises(EvidenceValidationError):
        validate_evidence_refs([invalid], {"json": document}, storage)


def test_event_locator_checks_quote_when_event_index_exists(tmp_path: Path):
    storage = LocalStorage(tmp_path)
    content = b'{"id":"event-1","text":"actual event"}\n'
    stored = storage.stage_bytes("batch", "events", content)
    storage.publish(stored.key, "evidence/batch/events")
    document = EvidenceDocument(
        file_id="events",
        name="events.jsonl",
        storage_key="evidence/batch/events",
        size_bytes=len(content),
        sha256=stored.sha256,
        parse_state="parsed",
        canonical_view={"kind": "jsonl", "line_count": 1, "event_ids": ["event-1"]},
        role="provenance",
        ignored=False,
        visibility="provenance",
    )
    invalid = AgentEvidenceRef(
        source_id="events",
        locator=EventLocator(event_id="event-1"),
        quote="not present",
    )
    with pytest.raises(EvidenceValidationError, match="event quote"):
        validate_evidence_refs([invalid], {"events": document}, storage)


def test_stateless_real_adapter_does_not_require_checkpoint_state():
    class StatelessGraph:
        def invoke(self, payload, **kwargs):
            assert "durability" not in kwargs
            assert kwargs["context"] == context
            return {"messages": [], "structured_response": CoverageReview().model_dump(mode="json")}

        def get_state(self, _config):
            pytest.fail("stateless adapters must not read checkpoint state")

    context = AgentRunContext(
        user_id="u",
        workspace_id="w",
        target_type="coverage",
        target_id="d",
        thread_key="coverage-thread",
        business_revision=0,
        evidence_file_ids=(),
        evidence_scope="/evidence/none",
        ai_profile_version="profile",
        graph_schema_version="graph",
    )
    result = DeepAgentsCoverageReviewer(
        model=ChatOpenAI(
            model="stateless-test",
            api_key="test-secret",
            base_url="https://models.example/v1",
            streaming=False,
        ),
        model_spec="openai:stateless-test",
    )._invoke(StatelessGraph(), {}, context, CoverageReview)
    assert isinstance(result.result, CoverageReview)


def test_production_graphs_construct_with_role_specific_tool_surfaces():
    profile = get_ai_profile()
    context = AgentRunContext(
        user_id="u",
        workspace_id="w",
        target_type="task",
        target_id="t",
        thread_key="thread-role-surface",
        business_revision=0,
        evidence_file_ids=(),
        evidence_scope="/evidence/task",
        ai_profile_version=profile.version,
        graph_schema_version="m0-cocreation-graph-v2",
    )
    model = ChatOpenAI(
        model="test-model",
        api_key="test-secret",
        base_url="https://models.example/v1",
        streaming=False,
    )
    model_spec = "openai:test-model"
    batch_graph = DeepAgentsEvidenceAnalyzer(model=model, model_spec=model_spec)._graph(
        context,
        {},
        BatchAnalysis,
        allowed_tools={"ls", "read_file", "glob", "grep", "BatchAnalysis"},
    )
    co_graph = DeepAgentsStandardCoCreator(model=model, model_spec=model_spec)._graph(
        context,
        {},
        CoCreationAgentResult,
        allowed_tools={"ls", "read_file", "glob", "grep", "ask_teacher", "CoCreationAgentResult"},
        ask_teacher=True,
    )
    batch_tools = set(getattr(batch_graph.nodes["tools"].bound, "_tools_by_name", {}))
    co_tools = set(getattr(co_graph.nodes["tools"].bound, "_tools_by_name", {}))
    assert "task" not in batch_tools
    assert not batch_tools & {"execute", "write_file", "edit_file", "delete"}
    assert "ask_teacher" in co_tools
    assert not co_tools & {"task", "execute", "write_file", "edit_file", "delete"}


def test_production_graph_explicitly_disables_empty_skill_and_memory_sources(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    def capture_create_deep_agent(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("deepagents.create_deep_agent", capture_create_deep_agent)
    model = ChatOpenAI(
        model="test-model",
        api_key="test-secret",
        base_url="https://models.example/v1",
        streaming=False,
    )
    adapter = DeepAgentsCoverageReviewer(model=model, model_spec="openai:test-model")
    context = AgentRunContext(
        user_id="u",
        workspace_id="w",
        target_type="coverage",
        target_id="t",
        thread_key="coverage-no-memory",
        business_revision=0,
        evidence_file_ids=(),
        evidence_scope="/evidence/none",
        ai_profile_version=get_ai_profile().version,
        graph_schema_version="m0-cocreation-graph-v2",
    )

    adapter._graph(context, {}, CoverageReview, allowed_tools={"CoverageReview"})

    assert captured["skills"] is None
    assert captured["memory"] is None
    assert captured["store"] is None


def test_teacher_can_split_groups_and_repeat_confirmation_without_duplicates(client: TestClient):
    workspace_id = _setup(client)
    upload = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches",
        data={"title": "可拆分任务包"},
        files=[
            ("files", ("first.md", BytesIO(b"first"), "text/markdown")),
            ("files", ("second.md", BytesIO(b"second"), "text/markdown")),
        ],
    )
    batch_id = upload.json()["batch"]["id"]
    assert default_worker().run_once().status.value == "succeeded"
    proposals = client.get(f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}/task-packages").json()
    ids = proposals["task_packages"][0]["evidence_file_ids"]
    batch_revision = proposals["batch_revision"]
    for file_id in ids:
        disposition = client.patch(
            f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}/files/{file_id}/disposition",
            json={"role": "runtime", "visibility": "runtime", "required": True, "batch_revision": batch_revision},
        )
        assert disposition.status_code == 200
        batch_revision += 1
    payload = {
        "command_id": "split-command",
        "batch_revision": batch_revision,
        "groups": [
            {"title": "任务 A", "evidence_file_ids": [ids[0]]},
            {"title": "任务 B", "evidence_file_ids": [ids[1]]},
        ],
    }
    first = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}/task-groups/confirmation",
        json=payload,
    )
    assert first.status_code == 200
    first_ids = [item["id"] for item in first.json()["task_packages"]]
    assert len(first_ids) == 2
    repeated = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}/task-groups/confirmation",
        json=payload,
    )
    assert repeated.status_code == 200
    assert [item["id"] for item in repeated.json()["task_packages"]] == first_ids
    assert "metadata" not in repeated.text
    assert len(cocreation_repository.list_task_packages(batch_id)) == 2


def test_cocreation_is_one_question_at_a_time_and_uses_stable_server_thread(client: TestClient):
    workspace_id, package_id, package_revision = _confirmed_package(client)
    started = client.post(
        f"/api/workspaces/{workspace_id}/task-packages/{package_id}/co-creation",
        json={"command_id": "start-contract", "kind": "scenario_contract", "task_package_revision": package_revision},
    )
    assert started.status_code == 202
    session_id = started.json()["session"]["id"]
    repeated = client.post(
        f"/api/workspaces/{workspace_id}/task-packages/{package_id}/co-creation",
        json={"command_id": "start-contract", "kind": "scenario_contract", "task_package_revision": package_revision},
    )
    assert repeated.json()["session"]["id"] == session_id
    assert default_worker().run_once().status.value == "succeeded"
    waiting = client.get(f"/api/workspaces/{workspace_id}/co-creation/{session_id}").json()["session"]
    assert waiting["next_action"] == "answer_question"
    assert waiting["pending_question"]
    assert "accepted_checkpoint_id" not in waiting
    assert "stable_thread_key" not in waiting
    assert len(waiting["turns"]) == 1

    stale = client.post(
        f"/api/workspaces/{workspace_id}/co-creation/{session_id}/answers",
        json={
            "command_id": "stale-answer",
            "question_id": waiting["pending_question"]["id"],
            "answer": "边界",
            "business_revision": waiting["business_revision"] - 1,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "STALE_COCREATION"

    answered = client.post(
        f"/api/workspaces/{workspace_id}/co-creation/{session_id}/answers",
        json={
            "command_id": "answer-1",
            "question_id": waiting["pending_question"]["id"],
            "answer": "边界",
            "business_revision": waiting["business_revision"],
        },
    )
    assert answered.status_code == 202
    duplicate = client.post(
        f"/api/workspaces/{workspace_id}/co-creation/{session_id}/answers",
        json={
            "command_id": "answer-1",
            "question_id": waiting["pending_question"]["id"],
            "answer": "边界",
            "business_revision": waiting["business_revision"],
        },
    )
    assert duplicate.status_code == 202
    assert duplicate.json()["session"]["business_revision"] == answered.json()["session"]["business_revision"]
    conflicting_answer = client.post(
        f"/api/workspaces/{workspace_id}/co-creation/{session_id}/answers",
        json={
            "command_id": "answer-1",
            "question_id": waiting["pending_question"]["id"],
            "answer": "不同回答",
            "business_revision": waiting["business_revision"],
        },
    )
    assert conflicting_answer.status_code == 409
    assert conflicting_answer.json()["error"]["code"] == "COMMAND_ID_REUSED"
    assert default_worker().run_once().status.value == "succeeded"
    second = client.get(f"/api/workspaces/{workspace_id}/co-creation/{session_id}").json()["session"]
    assert second["next_action"] == "answer_question"
    assert len(second["turns"]) == 2
    record = cocreation_repository.get_session(session_id)
    assert record is not None and record.accepted_checkpoint_id


def test_cocreation_completion_requires_teacher_confirmation_and_survives_checkpoint_delete(client: TestClient):
    workspace_id, package_id, package_revision = _confirmed_package(client)
    start = client.post(
        f"/api/workspaces/{workspace_id}/task-packages/{package_id}/co-creation",
        json={"command_id": "start-contract-2", "kind": "scenario_contract", "task_package_revision": package_revision},
    ).json()["session"]
    session_id = start["id"]
    assert default_worker().run_once().status.value == "succeeded"
    for command_id in ("answer-a", "answer-b"):
        session = client.get(f"/api/workspaces/{workspace_id}/co-creation/{session_id}").json()["session"]
        response = client.post(
            f"/api/workspaces/{workspace_id}/co-creation/{session_id}/answers",
            json={
                "command_id": command_id,
                "question_id": session["pending_question"]["id"],
                "answer": "老师确认的规则",
                "business_revision": session["business_revision"],
            },
        )
        assert response.status_code == 202
        assert default_worker().run_once().status.value == "succeeded"
    ready = client.get(f"/api/workspaces/{workspace_id}/co-creation/{session_id}").json()["session"]
    assert ready["status"] == "ready_for_confirmation"
    assert ready["next_action"] == "review_and_confirm"
    confirmed = client.post(
        f"/api/workspaces/{workspace_id}/co-creation/{session_id}/contract-confirmation",
        json={"command_id": "contract-confirm", "business_revision": ready["business_revision"]},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["session"]["status"] == "confirmed"
    package = client.get(f"/api/workspaces/{workspace_id}/task-packages/{package_id}").json()["task_package"]
    feedback = client.post(
        f"/api/workspaces/{workspace_id}/task-packages/{package_id}/feedback",
        json={"source_id": package["evidence_file_ids"][0], "text": "关键事实必须逐项回查。"},
    )
    assert feedback.status_code == 200
    promotion = client.post(
        f"/api/workspaces/{workspace_id}/standard-promotions/{feedback.json()['promotion_id']}/decision",
        json={"decision": "approve"},
    )
    assert promotion.status_code == 200
    assert len(cocreation_repository.list_contract_revisions(workspace_id)) == 2
    record = cocreation_repository.get_session(session_id)
    assert record is not None
    adapter = get_adapters().standard_cocreator
    adapter.checkpoints.delete_thread(record.stable_thread_key)  # type: ignore[attr-defined]
    still_there = client.get(f"/api/workspaces/{workspace_id}/co-creation/{session_id}")
    assert still_there.status_code == 200
    assert still_there.json()["session"]["status"] == "confirmed"


def test_judgment_cocreation_waits_for_confirmed_contract(client: TestClient):
    workspace_id, package_id, package_revision = _confirmed_package(client)
    blocked = client.post(
        f"/api/workspaces/{workspace_id}/task-packages/{package_id}/co-creation",
        json={"command_id": "judgment-before-contract", "kind": "task_judgment", "task_package_revision": package_revision},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "CONTRACT_NOT_CONFIRMED"


def test_missing_accepted_checkpoint_requires_explicit_continuity_reset(client: TestClient):
    workspace_id, package_id, package_revision = _confirmed_package(client)
    session = client.post(
        f"/api/workspaces/{workspace_id}/task-packages/{package_id}/co-creation",
        json={"command_id": "reset-start", "kind": "scenario_contract", "task_package_revision": package_revision},
    ).json()["session"]
    old_id = session["id"]
    assert default_worker().run_once().status.value == "succeeded"
    waiting = client.get(f"/api/workspaces/{workspace_id}/co-creation/{old_id}").json()["session"]
    record = cocreation_repository.get_session(old_id)
    assert record is not None
    get_adapters().standard_cocreator.checkpoints.delete_thread(record.stable_thread_key)  # type: ignore[attr-defined]
    answer = client.post(
        f"/api/workspaces/{workspace_id}/co-creation/{old_id}/answers",
        json={
            "command_id": "reset-answer",
            "question_id": waiting["pending_question"]["id"],
            "answer": "继续",
            "business_revision": waiting["business_revision"],
        },
    )
    assert answer.status_code == 202
    failed = default_worker().run_once()
    assert failed is not None and failed.status.value == "failed"
    old = cocreation_repository.get_session(old_id)
    assert old is not None and old.status == "continuity_reset"
    assert client.get(f"/api/workspaces/{workspace_id}/co-creation/{old_id}").json()["session"]["next_action"] == "continuity_reset"
    reset = client.post(
        f"/api/workspaces/{workspace_id}/co-creation/{old_id}/continuity-reset",
        json={"command_id": "reset-command", "reason": "旧 Checkpoint 已删除"},
    )
    assert reset.status_code == 202
    new_id = reset.json()["session"]["id"]
    assert new_id != old_id
    assert default_worker().run_once().status.value == "succeeded"
    assert client.get(f"/api/workspaces/{workspace_id}/co-creation/{new_id}").json()["session"]["next_action"] == "answer_question"


def test_operation_attempt_keeps_checkpoint_pointers_for_cocreation(client: TestClient):
    workspace_id, package_id, package_revision = _confirmed_package(client)
    start = client.post(
        f"/api/workspaces/{workspace_id}/task-packages/{package_id}/co-creation",
        json={"command_id": "pointer-start", "kind": "scenario_contract", "task_package_revision": package_revision},
    ).json()["session"]
    job = operation_repository.list_for_target("co_creation_session", start["id"])[0]
    assert default_worker().run_once().status.value == "succeeded"
    attempts = attempt_repository.list_for_job(job.id)
    assert len(attempts) == 1
    assert attempts[0].produced_checkpoint_id
    assert attempts[0].result_hash and len(attempts[0].result_hash) == 64


def test_reclaimed_cocreation_attempt_cannot_project_old_worker_result(client: TestClient):
    workspace_id, package_id, package_revision = _confirmed_package(client)
    start = client.post(
        f"/api/workspaces/{workspace_id}/task-packages/{package_id}/co-creation",
        json={"command_id": "reclaim-start", "kind": "scenario_contract", "task_package_revision": package_revision},
    )
    assert start.status_code == 202
    session_id = start.json()["session"]["id"]
    job = operation_repository.list_for_target("co_creation_session", session_id)[0]
    old_worker = operation_repository.claim_next("old-worker", lease_seconds=0)
    new_worker = operation_repository.claim_next("new-worker", lease_seconds=60)
    assert old_worker is not None and new_worker is not None
    assert old_worker.id == new_worker.id
    assert old_worker.attempts == 1
    assert new_worker.attempts == 2

    with pytest.raises(SupersededOperation):
        cocreation_service._run_cocreation_agent(old_worker, "start")

    session = cocreation_repository.get_session(session_id)
    assert session is not None
    assert session.status == "queued"
    assert session.projection is None
    attempts = attempt_repository.list_for_job(job.id)
    assert [item.produced_checkpoint_id for item in attempts] == [None, None]


def test_judgment_session_from_old_contract_cannot_be_confirmed(client: TestClient):
    workspace_id, package_id, package_revision = _confirmed_package(client)
    contract = client.post(
        f"/api/workspaces/{workspace_id}/task-packages/{package_id}/co-creation",
        json={"command_id": "contract-for-stale-judgment", "kind": "scenario_contract", "task_package_revision": package_revision},
    )
    assert contract.status_code == 202
    contract_id = contract.json()["session"]["id"]
    assert default_worker().run_once().status.value == "succeeded"
    contract_session = client.get(f"/api/workspaces/{workspace_id}/co-creation/{contract_id}").json()["session"]
    assert contract_session["next_action"] == "answer_question"
    answer = client.post(
        f"/api/workspaces/{workspace_id}/co-creation/{contract_id}/answers",
        json={
            "command_id": "contract-for-stale-judgment-answer",
            "question_id": contract_session["pending_question"]["id"],
            "answer": "先确定共同任务边界。",
            "business_revision": contract_session["business_revision"],
        },
    )
    assert answer.status_code == 202
    assert default_worker().run_once().status.value == "succeeded"
    contract_session = client.get(f"/api/workspaces/{workspace_id}/co-creation/{contract_id}").json()["session"]
    assert contract_session["next_action"] == "answer_question"
    answer = client.post(
        f"/api/workspaces/{workspace_id}/co-creation/{contract_id}/answers",
        json={
            "command_id": "contract-for-stale-judgment-answer-2",
            "question_id": contract_session["pending_question"]["id"],
            "answer": "硬门禁必须可回查。",
            "business_revision": contract_session["business_revision"],
        },
    )
    assert answer.status_code == 202
    assert default_worker().run_once().status.value == "succeeded"
    contract_session = client.get(f"/api/workspaces/{workspace_id}/co-creation/{contract_id}").json()["session"]
    confirmed_contract = client.post(
        f"/api/workspaces/{workspace_id}/co-creation/{contract_id}/contract-confirmation",
        json={"command_id": "contract-for-stale-judgment-confirm", "business_revision": contract_session["business_revision"]},
    )
    assert confirmed_contract.status_code == 200

    current_package = client.get(f"/api/workspaces/{workspace_id}/task-packages/{package_id}").json()["task_package"]
    judgment = client.post(
        f"/api/workspaces/{workspace_id}/task-packages/{package_id}/co-creation",
        json={"command_id": "stale-judgment", "kind": "task_judgment", "task_package_revision": current_package["revision"]},
    )
    assert judgment.status_code == 202
    judgment_id = judgment.json()["session"]["id"]
    assert default_worker().run_once().status.value == "succeeded"
    for index in range(2):
        pending = client.get(f"/api/workspaces/{workspace_id}/co-creation/{judgment_id}").json()["session"]
        response = client.post(
            f"/api/workspaces/{workspace_id}/co-creation/{judgment_id}/answers",
            json={
                "command_id": f"stale-judgment-answer-{index}",
                "question_id": pending["pending_question"]["id"],
                "answer": f"判定依据第 {index + 1} 轮。",
                "business_revision": pending["business_revision"],
            },
        )
        assert response.status_code == 202
        assert default_worker().run_once().status.value == "succeeded"
    ready = client.get(f"/api/workspaces/{workspace_id}/co-creation/{judgment_id}").json()["session"]
    assert ready["status"] == "ready_for_confirmation"

    new_contract = client.post(
        f"/api/workspaces/{workspace_id}/task-packages/{package_id}/co-creation",
        json={"command_id": "contract-for-stale-judgment-2", "kind": "scenario_contract", "task_package_revision": current_package["revision"]},
    )
    assert new_contract.status_code == 202
    new_contract_id = new_contract.json()["session"]["id"]
    assert default_worker().run_once().status.value == "succeeded"
    for index in range(2):
        pending = client.get(f"/api/workspaces/{workspace_id}/co-creation/{new_contract_id}").json()["session"]
        response = client.post(
            f"/api/workspaces/{workspace_id}/co-creation/{new_contract_id}/answers",
            json={
                "command_id": f"contract-for-stale-judgment-2-answer-{index}",
                "question_id": pending["pending_question"]["id"],
                "answer": f"新合同第 {index + 1} 轮。",
                "business_revision": pending["business_revision"],
            },
        )
        assert response.status_code == 202
        assert default_worker().run_once().status.value == "succeeded"
    new_contract_session = client.get(f"/api/workspaces/{workspace_id}/co-creation/{new_contract_id}").json()["session"]
    confirmed_new = client.post(
        f"/api/workspaces/{workspace_id}/co-creation/{new_contract_id}/contract-confirmation",
        json={"command_id": "contract-for-stale-judgment-2-confirm", "business_revision": new_contract_session["business_revision"]},
    )
    assert confirmed_new.status_code == 200
    updated_package = client.get(f"/api/workspaces/{workspace_id}/task-packages/{package_id}").json()["task_package"]

    rejected = client.post(
        f"/api/workspaces/{workspace_id}/co-creation/{judgment_id}/judgment-confirmation",
        json={"command_id": "stale-judgment-confirm", "business_revision": ready["business_revision"]},
    )
    assert rejected.status_code == 409
    assert client.get(f"/api/workspaces/{workspace_id}/task-packages/{package_id}").json()["task_package"]["has_judgment_package"] is False
    restarted = client.post(
        f"/api/workspaces/{workspace_id}/task-packages/{package_id}/co-creation",
        json={"command_id": "fresh-judgment", "kind": "task_judgment", "task_package_revision": updated_package["revision"]},
    )
    assert restarted.status_code == 202
    assert restarted.json()["session"]["id"] != judgment_id


def test_projection_pending_reprojects_checkpoint_without_new_agent_call(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    workspace_id, package_id, package_revision = _confirmed_package(client)
    counting = FakeStandardCoCreator()
    calls = {"start": 0, "resume": 0, "reproject": 0}

    original_start = counting.start
    original_reproject = counting.reproject

    def start(*args, **kwargs):
        calls["start"] += 1
        return original_start(*args, **kwargs)

    def reproject(*args, **kwargs):
        calls["reproject"] += 1
        return original_reproject(*args, **kwargs)

    counting.start = start  # type: ignore[method-assign]
    counting.reproject = reproject  # type: ignore[method-assign]
    set_adapters(RuntimeAdapters(FakeEvidenceAnalyzer(), counting, FakeCoverageReviewer()))

    start_response = client.post(
        f"/api/workspaces/{workspace_id}/task-packages/{package_id}/co-creation",
        json={"command_id": "projection-start", "kind": "scenario_contract", "task_package_revision": package_revision},
    )
    session_id = start_response.json()["session"]["id"]
    original_commit = cocreation_repository.commit_agent_result
    failed_once = {"value": True}

    def fail_projection(*args, **kwargs):
        if failed_once["value"]:
            failed_once["value"] = False
            raise RuntimeError("simulated projection transaction failure")
        return original_commit(*args, **kwargs)

    monkeypatch.setattr(cocreation_repository, "commit_agent_result", fail_projection)
    pending = default_worker().run_once()
    assert pending is not None and pending.status.value == "projection_pending"
    record = cocreation_repository.get_session(session_id)
    assert record is not None and record.status == "projection_pending"
    assert calls == {"start": 1, "resume": 0, "reproject": 0}

    retry = client.post(
        f"/api/workspaces/{workspace_id}/co-creation/{session_id}/retry",
        json={"command_id": "projection-retry", "business_revision": record.business_revision},
    )
    assert retry.status_code == 202
    finished = default_worker().run_once()
    assert finished is not None and finished.status.value == "succeeded"
    assert calls == {"start": 1, "resume": 0, "reproject": 1}
    recovered = client.get(f"/api/workspaces/{workspace_id}/co-creation/{session_id}")
    assert recovered.status_code == 200
    assert recovered.json()["session"]["status"] == "waiting_for_teacher"
    assert recovered.json()["session"]["next_action"] == "answer_question"
