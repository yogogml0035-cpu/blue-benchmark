from __future__ import annotations

from uuid import uuid4
from datetime import datetime, timezone
import json

from fastapi.testclient import TestClient
import pytest

from app.features.case_builder.authoring_schemas import BadSample, InputAnswerPatchRequest, QuestionInput
from app.features.case_builder import authoring_repository
from app.features.evaluation_sets import rubric_repository
from app.features.evaluation_sets import lifecycle_service
from app.lib.ai_runtime import reset_adapters
from app.lib.database import clear_business_data
from app.lib.operations.worker import default_worker
from app.lib.version_packages.v2 import QuestionRevisionPackageTask, build_question_revision_package
from app.main import app
from tests.test_rubric_publishing import _confirmed_question, _start_and_generate


@pytest.fixture(autouse=True)
def reset_state():
    clear_business_data()
    reset_adapters()
    yield
    reset_adapters()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_bad_sample_contract_rejects_private_trace_and_keeps_teacher_evidence():
    sample = BadSample(
        id="bad-1",
        source_ref="真实执行 2026-09-01 · 第 1 次结果",
        content_text="这是一份老师实际看到并否定的结果。",
        teacher_feedback_texts=["关键事实没有依据。"],
        reason_summary="核心事实不能回到确认材料。",
    )
    assert sample.teacher_feedback_texts == ["关键事实没有依据。"]
    exact = BadSample(
        id="bad-exact",
        source_ref="真实执行",
        content_text="结果原文",
        teacher_feedback_texts=["  老师原话前后空白仍需保留。  "],
        reason_summary="原因摘要",
    )
    assert exact.teacher_feedback_texts == ["  老师原话前后空白仍需保留。  "]
    with pytest.raises(ValueError):
        BadSample(
            id="bad-private",
            source_ref="真实执行",
            content_text="system_prompt: hidden",
            teacher_feedback_texts=["不合格。"],
            reason_summary="没有满足要求。",
        )
    raw = "  请保留原始任务要求的前后空白。\n不要改写。  "
    assert QuestionInput(task_instruction=raw).task_instruction == raw
    patch = InputAnswerPatchRequest(
        command_id="raw-answer",
        draft_revision=1,
        input=QuestionInput(task_instruction=raw),
        reference_answer_text="  老师认可的原始终版。\n  ",
    )
    assert patch.reference_answer_text == "  老师认可的原始终版。\n  "


def test_bad_samples_are_judge_provenance_only_in_v2_package():
    bad_sample = {
        "id": "bad-1",
        "source_ref": "真实执行",
        "content_text": "老师实际看到的错误结果。",
        "teacher_feedback_texts": ["关键事实没有依据。"],
        "reason_summary": "不能回到确认材料。",
    }
    artifacts = build_question_revision_package(
        version_id="version-1",
        workspace_id="workspace-1",
        version_number=1,
        contract_revision=0,
        contract_revision_id=None,
        contract={},
        coverage={"automatic": True},
        tasks=[
            QuestionRevisionPackageTask(
                task_id="question-1",
                revision=1,
                title="事实题",
                brief="根据资料形成结果。",
                input={"task_instruction": "根据资料形成结果。", "must_include": [], "prohibited": [], "background": None, "materials": []},
                files=(),
                judge={"reference_answer_text": "标准答案。", "bad_samples": [bad_sample], "rubric": {}},
                provenance={"bad_samples": [bad_sample]},
            )
        ],
        frozen_by="user-1",
        frozen_at=datetime.now(timezone.utc),
        risk_confirmation={"automatic": True},
    )
    runtime = json.loads(artifacts.runtime_bytes)
    judge = json.loads(artifacts.judge_bytes)
    provenance = json.loads(artifacts.provenance_bytes)
    assert "bad_samples" not in json.dumps(runtime, ensure_ascii=False)
    assert "bad_samples" in json.dumps(judge, ensure_ascii=False)
    assert "bad_samples" in json.dumps(provenance, ensure_ascii=False)


def test_confirm_and_start_rubric_is_one_server_action(client: TestClient):
    workspace_id, question_draft_id, _conversation_id, confirmed_revision = _confirmed_question(client)
    response = client.post(
        f"/api/workspaces/{workspace_id}/authoring/question-drafts/{question_draft_id}/rubric/start",
        json={"command_id": f"confirm-start-{uuid4().hex}", "question_revision": confirmed_revision},
    )
    assert response.status_code == 202, response.text
    assert response.json()["rubric"]["next_action"] == "wait_for_processing"
    assert default_worker().run_once() is not None


def test_automatic_publish_enters_current_set_and_is_idempotent(client: TestClient):
    workspace_id, question_draft_id, generated = _start_and_generate(client)
    command_id = f"automatic-publish-{uuid4().hex}"
    response = client.post(
        f"/api/workspaces/{workspace_id}/authoring/question-drafts/{question_draft_id}/rubric/publish",
        json={
            "command_id": command_id,
            "rubric_revision": generated["revision"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()["rubric"]
    revision_id = body["published_revision_id"]
    assert body["status"] == "published"
    revision = rubric_repository.get_revision(revision_id)
    assert revision is not None
    questions = client.get(f"/api/workspaces/{workspace_id}/questions")
    assert questions.status_code == 200, questions.text
    question_view = next(item for item in questions.json()["questions"] if item["id"] == question_draft_id)
    assert question_view["lifecycle_status"] == "active"
    assert question_view["active_revision_id"] == revision_id

    versions = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/versions")
    assert versions.status_code == 200, versions.text
    assert len(versions.json()["versions"]) == 1
    version_id = versions.json()["versions"][0]["id"]
    manifest = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/versions/{version_id}/manifest")
    assert manifest.status_code == 200, manifest.text
    assert manifest.json()["manifest"]["schema_version"] == "m0-evaluation-package-v2"
    assert manifest.json()["manifest"]["tasks"][0]["question_revision_id"] == revision_id

    repeated = client.post(
        f"/api/workspaces/{workspace_id}/authoring/question-drafts/{question_draft_id}/rubric/publish",
        json={
            "command_id": command_id,
            "rubric_revision": generated["revision"],
        },
    )
    assert repeated.status_code == 200, repeated.text
    versions_after = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/versions")
    assert len(versions_after.json()["versions"]) == 1


def test_automatic_publish_package_failure_stays_in_review(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    workspace_id, question_draft_id, generated = _start_and_generate(client)

    def fail_builder(*args, **kwargs):
        raise RuntimeError("simulated automatic package failure")

    monkeypatch.setattr(lifecycle_service, "build_question_revision_package", fail_builder)
    response = client.post(
        f"/api/workspaces/{workspace_id}/authoring/question-drafts/{question_draft_id}/rubric/publish",
        json={"command_id": f"automatic-failure-{uuid4().hex}", "rubric_revision": generated["revision"]},
    )
    assert response.status_code == 503, response.text
    assert rubric_repository.list_published_revisions(workspace_id) == []
    assert client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/versions").json()["versions"] == []


def test_disable_restore_delete_change_current_set_but_keep_history_readable(client: TestClient):
    workspace_id, question_draft_id, generated = _start_and_generate(client)
    command_id = f"lifecycle-publish-{uuid4().hex}"
    published = client.post(
        f"/api/workspaces/{workspace_id}/authoring/question-drafts/{question_draft_id}/rubric/publish",
        json={"command_id": command_id, "rubric_revision": generated["revision"]},
    )
    assert published.status_code == 200, published.text
    revision_id = published.json()["rubric"]["published_revision_id"]
    submission = client.post(
        f"/api/workspaces/{workspace_id}/question-revisions/{revision_id}/submissions",
        json={"command_id": f"history-submission-{uuid4().hex}", "content_text": "停用前已经存在的待评结果。"},
    )
    assert submission.status_code == 201, submission.text

    # Resolve the parent conversation through the authoring projection without
    # exposing an internal conversation identifier in the lifecycle contract.
    from app.features.case_builder import authoring_repository

    conversation = authoring_repository.get_conversation_by_draft(question_draft_id)
    assert conversation is not None
    path = f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation.id}/question-drafts/{question_draft_id}/lifecycle"
    draft = authoring_repository.get_draft(question_draft_id)
    assert draft is not None and draft.lifecycle_status == "active"

    disabled = client.post(
        path,
        json={"command_id": f"disable-{uuid4().hex}", "draft_revision": draft.revision, "action": "disable"},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["conversation"]["question_drafts"][0]["lifecycle_status"] == "disabled"
    blocked = client.post(
        f"/api/workspaces/{workspace_id}/question-revisions/{revision_id}/submissions",
        json={"command_id": f"blocked-{uuid4().hex}", "content_text": "停用后不能新增。"},
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["code"] == "QUESTION_NOT_ACTIVE"
    assert client.get(f"/api/workspaces/{workspace_id}/submissions/{submission.json()['submission']['id']}").status_code == 200

    draft = authoring_repository.get_draft(question_draft_id)
    assert draft is not None
    restored = client.post(
        path,
        json={"command_id": f"restore-{uuid4().hex}", "draft_revision": draft.revision, "action": "restore"},
    )
    assert restored.status_code == 200, restored.text
    reopened = client.post(
        f"/api/workspaces/{workspace_id}/question-revisions/{revision_id}/submissions",
        json={"command_id": f"reopened-{uuid4().hex}", "content_text": "恢复后可以新增。"},
    )
    assert reopened.status_code == 201, reopened.text

    draft = authoring_repository.get_draft(question_draft_id)
    assert draft is not None
    deleted = client.post(
        path,
        json={"command_id": f"delete-{uuid4().hex}", "draft_revision": draft.revision, "action": "delete"},
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["conversation"]["question_drafts"][0]["lifecycle_status"] == "deleted"
    cannot_restore = client.post(
        path,
        json={"command_id": f"restore-deleted-{uuid4().hex}", "draft_revision": draft.revision, "action": "restore"},
    )
    assert cannot_restore.status_code == 409, cannot_restore.text
    assert client.get(f"/api/workspaces/{workspace_id}/submissions/{submission.json()['submission']['id']}").status_code == 200


def test_lifecycle_package_failure_does_not_commit_visible_state(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    workspace_id, question_draft_id, generated = _start_and_generate(client)
    published = client.post(
        f"/api/workspaces/{workspace_id}/authoring/question-drafts/{question_draft_id}/rubric/publish",
        json={"command_id": f"failure-publish-{uuid4().hex}", "rubric_revision": generated["revision"]},
    )
    assert published.status_code == 200, published.text
    conversation = authoring_repository.get_conversation_by_draft(question_draft_id)
    draft = authoring_repository.get_draft(question_draft_id)
    assert conversation is not None and draft is not None
    original_builder = lifecycle_service.build_question_revision_package

    def fail_builder(*args, **kwargs):
        raise RuntimeError("simulated package failure")

    monkeypatch.setattr(lifecycle_service, "build_question_revision_package", fail_builder)
    response = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation.id}/question-drafts/{question_draft_id}/lifecycle",
        json={"command_id": f"failure-disable-{uuid4().hex}", "draft_revision": draft.revision, "action": "disable"},
    )
    assert response.status_code == 503, response.text
    after = authoring_repository.get_draft(question_draft_id)
    assert after is not None
    assert after.lifecycle_status == "active"
    assert after.lifecycle_pending is None
    assert len(client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/versions").json()["versions"]) == 1
    monkeypatch.setattr(lifecycle_service, "build_question_revision_package", original_builder)
