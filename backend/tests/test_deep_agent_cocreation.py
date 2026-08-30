from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.features.auth import repository as auth_repository
from app.features.case_builder import cocreation_repository
from app.features.case_builder import ingestion_repository
from app.features.workspaces import repository as workspace_repository
from app.lib.ai_runtime import get_adapters, reset_adapters, set_adapters
from app.lib.ai_runtime.adapters import (
    FakeCoverageReviewer,
    FakeEvidenceAnalyzer,
    FakeStandardCoCreator,
    RuntimeAdapters,
)
from app.lib.ai_runtime.evidence import EvidenceDocument, ReadOnlyEvidenceBackend
from app.lib.ai_runtime.middleware import ModelToolSurfaceMiddleware
from app.lib.ai_runtime.adapters import _question_from_interrupt
from langchain.agents.middleware.types import ToolCallRequest
from app.lib.database import clear_business_data
from app.lib.operations import attempts as attempt_repository
from app.lib.operations import repository as operation_repository
from app.lib.operations.worker import default_worker
from app.lib.storage import LocalStorage
from app.main import app


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
    assert first.total_lines == 130
    assert first.next_offset == 100
    assert "line-100" in (first.file_data or {})["content"]
    assert tail.next_offset is None
    assert "line-130" in (tail.file_data or {})["content"]
    assert backend.read("/etc/passwd").error
    assert backend.write("/evidence/file", "overwrite").error
    assert backend.edit("/evidence/file", "line-1", "changed").error
    assert backend.delete("/evidence/file").error
    assert backend.grep("line-130", path="/evidence").matches[0]["line"] == 130


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
