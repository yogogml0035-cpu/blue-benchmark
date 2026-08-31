from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.features.auth import repository as auth_repository
from app.features.case_builder import authoring_repository
from app.features.case_builder import ingestion_repository
from app.lib.ai_runtime import reset_adapters
from app.lib.database import clear_business_data
from app.lib.operations import repository as operation_repository
from app.lib.operations.worker import ProjectionPendingOperation, default_worker
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


def _setup(client: TestClient, username: str | None = None) -> str:
    name = username or f"authoring-{uuid4().hex[:8]}"
    registered = client.post(
        "/api/auth/register",
        json={"username": name, "email": f"{name}@example.com", "password": "password123"},
    )
    assert registered.status_code == 201, registered.text
    workspace = client.post("/api/workspaces", json={"name": "建题场景"})
    assert workspace.status_code == 201, workspace.text
    return workspace.json()["workspace"]["id"]


def _create(client: TestClient, workspace_id: str, **overrides):
    payload = {
        "command_id": f"create-{uuid4()}",
        "title": "媒体供稿题",
        "task_instruction": "请根据老师确认的资料形成一份事实准确的供稿。",
        **overrides,
    }
    response = client.post(f"/api/workspaces/{workspace_id}/authoring-conversations", json=payload)
    assert response.status_code == 202, response.text
    return response.json()["conversation"]


def _finish_candidate_discovery(client: TestClient, workspace_id: str, conversation_id: str):
    finished = default_worker().run_once()
    assert finished is not None and finished.status.value == "succeeded"
    response = client.get(f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation_id}")
    assert response.status_code == 200, response.text
    return response.json()["conversation"]


def test_authoring_conversation_create_get_and_safe_events(client: TestClient):
    workspace_id = _setup(client)
    created = _create(client, workspace_id)
    assert created["status"] == "processing"
    conversation_id = created["id"]

    recovered = _finish_candidate_discovery(client, workspace_id, conversation_id)
    assert recovered["status"] == "review_ready"
    assert recovered["next_action"] == "confirm_question_boundaries"
    assert len(recovered["question_drafts"]) == 1
    assert recovered["messages"][-1]["role"] == "assistant"
    assert "候选题" in recovered["messages"][-1]["content"]

    stream = client.get(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation_id}/events"
    )
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "public_message_ready" in stream.text
    assert "storage_key" not in stream.text
    assert "thread" not in stream.text.casefold()
    assert "checkpoint" not in stream.text.casefold()

    event_cursor = recovered["events_cursor"]
    replay = client.get(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation_id}/events?after={event_cursor}"
    )
    assert replay.status_code == 200
    assert replay.text.startswith(": heartbeat")


def test_one_message_is_active_and_second_message_returns_409(client: TestClient):
    workspace_id = _setup(client)
    created = _create(client, workspace_id)
    conversation_id = created["id"]
    current = _finish_candidate_discovery(client, workspace_id, conversation_id)

    first = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation_id}/messages",
        json={
            "command_id": "teacher-message-1",
            "conversation_revision": current["revision"],
            "content": "请把任务边界聚焦到新闻稿交付。",
        },
    )
    assert first.status_code == 202, first.text
    assert first.json()["conversation"]["status"] == "processing"

    second = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation_id}/messages",
        json={
            "command_id": "teacher-message-2",
            "conversation_revision": current["revision"],
            "content": "另一条不能排队的消息。",
        },
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "AUTHORING_ACTIVE"


def test_manual_multi_question_boundary_and_single_teacher_answer_confirmation(client: TestClient):
    workspace_id = _setup(client)
    created = _create(
        client,
        workspace_id,
        title="多题聊天",
        task_instruction="任务A：写一份新闻稿\n任务B：写一封邀请函",
    )
    current = _finish_candidate_discovery(client, workspace_id, created["id"])
    drafts = current["question_drafts"]
    assert len(drafts) == 2
    assert {item["title"] for item in drafts} == {"写一份新闻稿", "写一封邀请函"}

    boundary = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/question-boundaries",
        json={
            "command_id": "confirm-boundaries-1",
            "conversation_revision": current["revision"],
            "action": "confirm",
            "draft_ids": [item["id"] for item in drafts],
        },
    )
    assert boundary.status_code == 200, boundary.text
    current = boundary.json()["conversation"]
    assert current["next_action"] == "wait_for_processing"
    assert default_worker().run_once() is not None
    current = client.get(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}"
    ).json()["conversation"]
    assert current["next_action"] == "provide_standard_answer"
    stored_question = authoring_repository.list_drafts(created["id"], include_discarded=False)[0]
    assert stored_question.question_checkpoint_id is not None
    assert stored_question.question_question_count == 1
    pending = current["pending_question"]
    assert pending["gap_type"] == "standard_answer"

    answer = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/messages",
        json={
            "command_id": "teacher-answer-1",
            "conversation_revision": current["revision"],
            "content": "这是老师明确认可的新闻稿终版。",
            "message_type": "standard_answer",
            "question_draft_id": pending["question_draft_id"],
        },
    )
    assert answer.status_code == 202, answer.text
    assert default_worker().run_once() is not None
    current = client.get(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}"
    ).json()["conversation"]
    resumed_question = next(
        item
        for item in authoring_repository.list_drafts(created["id"], include_discarded=False)
        if item.id == pending["question_draft_id"]
    )
    assert resumed_question.question_checkpoint_id is None
    answered = next(item for item in current["question_drafts"] if item["id"] == pending["question_draft_id"])
    untouched = next(item for item in current["question_drafts"] if item["id"] != pending["question_draft_id"])
    assert answered["reference_answer_text"] == "这是老师明确认可的新闻稿终版。"
    assert untouched["reference_answer_text"] is None

    # Confirmation is explicit and only one teacher answer is stored for the
    # selected draft; it cannot be inferred from the latest assistant message.
    first_confirmation = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/question-drafts/{answered['id']}/input-answer-confirmation",
        json={"command_id": "confirm-without-roles", "draft_revision": answered["revision"]},
    )
    assert first_confirmation.status_code == 200, first_confirmation.text
    assert first_confirmation.json()["conversation"]["status"] == "review_ready"
    assert first_confirmation.json()["conversation"]["next_action"] == "provide_standard_answer"


def test_manual_message_without_task_field_is_used_for_multi_question_discovery(client: TestClient):
    workspace_id = _setup(client)
    created = _create(
        client,
        workspace_id,
        task_instruction=None,
        message="任务A：写一份新闻稿\n任务B：写一封邀请函",
    )
    current = _finish_candidate_discovery(client, workspace_id, created["id"])
    assert {item["title"] for item in current["question_drafts"]} == {"写一份新闻稿", "写一封邀请函"}


def test_unscoped_initial_standard_answer_is_not_assigned_to_one_of_many_questions(client: TestClient):
    workspace_id = _setup(client)
    created = _create(
        client,
        workspace_id,
        task_instruction="任务A：写一份新闻稿\n任务B：写一封邀请函",
        reference_answer_text="这份答案没有指定对应题目。",
    )
    current = _finish_candidate_discovery(client, workspace_id, created["id"])
    assert all(item["reference_answer_text"] is None for item in current["question_drafts"])
    assert current["next_action"] == "confirm_question_boundaries"


def test_same_message_command_is_idempotent_and_cross_workspace_is_forbidden(client: TestClient):
    workspace_id = _setup(client, "authoring-owner")
    created = _create(client, workspace_id)
    current = _finish_candidate_discovery(client, workspace_id, created["id"])
    payload = {
        "command_id": "same-message",
        "conversation_revision": current["revision"],
        "content": "请保留事实边界。",
    }
    first = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/messages",
        json=payload,
    )
    assert first.status_code == 202
    # A duplicate command is replay-safe even while the first operation is queued.
    duplicate = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/messages",
        json=payload,
    )
    assert duplicate.status_code == 202
    assert duplicate.json()["conversation"]["revision"] == first.json()["conversation"]["revision"]

    other = TestClient(app)
    other_registered = other.post(
        "/api/auth/register",
        json={"username": "authoring-other", "email": "authoring-other@example.com", "password": "password123"},
    )
    assert other_registered.status_code == 201
    forbidden = other.get(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}"
    )
    assert forbidden.status_code == 403


def test_teacher_message_command_cannot_be_reused_in_another_conversation(client: TestClient):
    workspace_id = _setup(client)
    first = _create(client, workspace_id, title="第一会话")
    second = _create(client, workspace_id, title="第二会话")
    assert default_worker().run_once() is not None
    assert default_worker().run_once() is not None
    for conversation in (first, second):
        current = client.get(
            f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation['id']}"
        ).json()["conversation"]
        if conversation is first:
            first_revision = current["revision"]
            first_id = conversation["id"]
        else:
            second_revision = current["revision"]
            second_id = conversation["id"]
    first_message = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{first_id}/messages",
        json={"command_id": "global-teacher-command", "conversation_revision": first_revision, "content": "第一会话补充。"},
    )
    assert first_message.status_code == 202
    second_message = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{second_id}/messages",
        json={"command_id": "global-teacher-command", "conversation_revision": second_revision, "content": "第二会话补充。"},
    )
    assert second_message.status_code == 409
    assert second_message.json()["error"]["code"] == "COMMAND_ID_REUSED"


def test_boundary_commands_are_replay_safe_and_upstream_message_invalidates_confirmation(client: TestClient):
    workspace_id = _setup(client)
    created = _create(
        client,
        workspace_id,
        reference_answer_text="老师确认的初版标准答案。",
    )
    current = _finish_candidate_discovery(client, workspace_id, created["id"])
    draft = current["question_drafts"][0]
    boundary_payload = {
        "command_id": "boundary-replay",
        "conversation_revision": current["revision"],
        "action": "confirm",
        "draft_ids": [draft["id"]],
    }
    first = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/question-boundaries",
        json=boundary_payload,
    )
    assert first.status_code == 200
    repeated = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/question-boundaries",
        json=boundary_payload,
    )
    assert repeated.status_code == 200
    assert repeated.json()["conversation"]["revision"] == first.json()["conversation"]["revision"]
    assert default_worker().run_once() is not None

    latest = client.get(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}"
    ).json()["conversation"]
    patch = client.patch(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/question-drafts/{draft['id']}/input-answer",
        json={
            "command_id": "draft-input-1",
            "draft_revision": latest["question_drafts"][0]["revision"],
            "input": {
                "task_instruction": "写一份事实准确的新闻稿。",
                "materials": [],
                "must_include": ["事实来源"],
                "prohibited": ["无来源推断"],
                "background": "老师确认的业务背景。",
            },
            "reference_answer_text": "老师确认的初版标准答案。",
        },
    )
    assert patch.status_code == 200, patch.text
    updated = patch.json()["conversation"]
    editable = updated["question_drafts"][0]
    confirmed = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/question-drafts/{draft['id']}/input-answer-confirmation",
        json={"command_id": "draft-confirm-1", "draft_revision": editable["revision"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["conversation"]["status"] == "confirmed"

    # A later teacher message creates a new upstream revision and clears the
    # confirmation, while preserving the teacher answer for re-review.
    changed = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/messages",
        json={
            "command_id": "upstream-change-1",
            "conversation_revision": confirmed.json()["conversation"]["revision"],
            "content": "请把禁用内容再收紧一些。",
        },
    )
    assert changed.status_code == 202
    invalidated = changed.json()["conversation"]["question_drafts"][0]
    assert invalidated["status"] == "input_answer_drafting"
    assert invalidated["confirmed_revision"] is None


def test_standard_answer_for_one_question_does_not_clear_another_confirmation(client: TestClient):
    workspace_id = _setup(client)
    created = _create(
        client,
        workspace_id,
        task_instruction="任务A：新闻稿\n任务B：邀请函",
    )
    current = _finish_candidate_discovery(client, workspace_id, created["id"])
    drafts = current["question_drafts"]
    boundary = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/question-boundaries",
        json={
            "command_id": "confirm-two-boundaries",
            "conversation_revision": current["revision"],
            "action": "confirm",
            "draft_ids": [item["id"] for item in drafts],
        },
    )
    current = boundary.json()["conversation"]
    assert current["next_action"] == "wait_for_processing"
    assert default_worker().run_once() is not None
    current = client.get(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}"
    ).json()["conversation"]
    first_id = current["pending_question"]["question_draft_id"]
    first_answer = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/messages",
        json={
            "command_id": "answer-first",
            "conversation_revision": current["revision"],
            "content": "第一题的老师终版。",
            "message_type": "standard_answer",
            "question_draft_id": first_id,
        },
    )
    assert first_answer.status_code == 202
    assert default_worker().run_once() is not None
    current = client.get(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}"
    ).json()["conversation"]
    first = next(item for item in current["question_drafts"] if item["id"] == first_id)
    second = next(item for item in current["question_drafts"] if item["id"] != first_id)
    confirmed = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/question-drafts/{first_id}/input-answer-confirmation",
        json={"command_id": "confirm-first", "draft_revision": first["revision"]},
    )
    assert confirmed.status_code == 200
    current = confirmed.json()["conversation"]
    second_answer = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/messages",
        json={
            "command_id": "answer-second",
            "conversation_revision": current["revision"],
            "content": "第二题的老师终版。",
            "message_type": "standard_answer",
            "question_draft_id": second["id"],
        },
    )
    assert second_answer.status_code == 202
    current = second_answer.json()["conversation"]
    first_after_message = next(item for item in current["question_drafts"] if item["id"] == first_id)
    assert first_after_message["status"] == "input_answer_confirmed"


def test_saving_a_teacher_answer_updates_the_pending_question_projection(client: TestClient):
    workspace_id = _setup(client)
    created = _create(client, workspace_id)
    current = _finish_candidate_discovery(client, workspace_id, created["id"])
    draft = current["question_drafts"][0]
    boundary = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/question-boundaries",
        json={
            "command_id": "pending-projection-boundary",
            "conversation_revision": current["revision"],
            "action": "confirm",
            "draft_ids": [draft["id"]],
        },
    )
    current = boundary.json()["conversation"]
    assert default_worker().run_once() is not None
    current = client.get(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}"
    ).json()["conversation"]
    editable = current["question_drafts"][0]
    saved = client.patch(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/question-drafts/{draft['id']}/input-answer",
        json={
            "command_id": "pending-projection-input",
            "draft_revision": editable["revision"],
            "input": {
                "task_instruction": "写一份事实准确的新闻稿。",
                "materials": [],
                "must_include": [],
                "prohibited": [],
                "background": None,
            },
            "reference_answer_text": "老师保存的终版答案。",
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["conversation"]["pending_question"] is None
    assert saved.json()["conversation"]["next_action"] == "confirm_input_answer"


def test_worker_attach_does_not_reactivate_a_terminal_job(client: TestClient):
    workspace_id = _setup(client)
    created = _create(client, workspace_id)
    jobs = operation_repository.list_for_target("authoring_conversation", created["id"])
    assert len(jobs) == 1
    job = operation_repository.claim_next("race-review-worker")
    assert job is not None
    operation_repository.complete(job.id, "race-review-worker", {"test": True})
    attached = authoring_repository.set_active_operation(
        created["id"],
        job.id,
        expected_revision=created["revision"],
    )
    assert attached.status == "failed"
    assert attached.active_operation_id is None


def test_retry_command_is_idempotent_after_the_conversation_has_advanced(client: TestClient):
    workspace_id = _setup(client)
    created = _create(client, workspace_id)
    worker = default_worker()

    def fail(_job):
        raise RuntimeError("synthetic authoring failure")

    worker.handlers["authoring_process"] = fail
    failed = worker.run_once()
    assert failed is not None and failed.status.value == "failed"
    current = client.get(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}"
    ).json()["conversation"]
    assert current["status"] == "failed"
    retry_payload = {
        "command_id": "retry-once",
        "conversation_revision": current["revision"],
    }
    first = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/retry",
        json=retry_payload,
    )
    assert first.status_code == 202
    default_worker().run_once()
    repeated = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/retry",
        json=retry_payload,
    )
    assert repeated.status_code == 202
    assert repeated.json()["conversation"]["revision"] == first.json()["conversation"]["revision"] + 1


def test_projection_pending_is_visible_as_a_recoverable_authoring_state(client: TestClient):
    workspace_id = _setup(client)
    created = _create(client, workspace_id)
    worker = default_worker()

    def pending(_job):
        raise ProjectionPendingOperation()

    worker.handlers["authoring_process"] = pending
    result = worker.run_once()
    assert result is not None and result.status.value == "projection_pending"
    current = client.get(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}"
    ).json()["conversation"]
    assert current["status"] == "projection_pending"
    assert current["next_action"] == "retry_processing"
    assert current["active_operation"]["status"] == "projection_pending"


def test_projection_pending_retries_from_saved_result_without_another_model_call(client: TestClient):
    workspace_id = _setup(client)
    created = _create(client, workspace_id)
    worker = default_worker()
    calls = 0

    def pending(job):
        nonlocal calls
        calls += 1
        assert job.worker_id is not None
        operation_repository.save_result(
            job.id,
            job.worker_id,
            {
                "__authoring_projection": {
                    "drafts": [],
                    "status": "review_ready",
                    "pending_question": None,
                    "assistant_message": "已恢复保存的建题结果。",
                    "events": [
                        [
                            "snapshot_changed",
                            {"revision": 1, "status": "review_ready", "draft_count": 0},
                        ]
                    ],
                }
            },
        )
        raise ProjectionPendingOperation()

    worker.handlers["authoring_process"] = pending
    first = worker.run_once()
    assert first is not None and first.status.value == "projection_pending"
    current = client.get(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}"
    ).json()["conversation"]
    retry = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/retry",
        json={"command_id": "reproject-from-saved", "conversation_revision": current["revision"]},
    )
    assert retry.status_code == 202, retry.text
    second = worker.run_once()
    assert second is not None and second.status.value == "succeeded"
    assert calls == 1
    recovered = client.get(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}"
    ).json()["conversation"]
    assert recovered["status"] == "review_ready"


def test_confirmation_is_rejected_while_the_authoring_operation_is_active(client: TestClient):
    workspace_id = _setup(client)
    created = _create(client, workspace_id)
    current = _finish_candidate_discovery(client, workspace_id, created["id"])
    draft = current["question_drafts"][0]
    boundary = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/question-boundaries",
        json={
            "command_id": "active-confirm-boundary",
            "conversation_revision": current["revision"],
            "action": "confirm",
            "draft_ids": [draft["id"]],
        },
    )
    current = boundary.json()["conversation"]
    assert current["next_action"] == "wait_for_processing"
    editable = current["question_drafts"][0]
    confirmation = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/question-drafts/{draft['id']}/input-answer-confirmation",
        json={"command_id": "active-confirm", "draft_revision": editable["revision"]},
    )
    assert confirmation.status_code == 409
    assert confirmation.json()["error"]["code"] == "AUTHORING_ACTIVE"


def test_safe_event_repository_rejects_internal_fields(client: TestClient):
    workspace_id = _setup(client)
    created = _create(client, workspace_id)
    with pytest.raises(ValueError, match="non-public|internal"):
        authoring_repository.append_event(
            created["id"],
            "action_summary",
            {"label": "读取", "count": 1, "storage_key": "/private/path"},
        )
    with pytest.raises(ValueError, match="internal|host path"):
        authoring_repository.append_event(
            created["id"],
            "public_message_ready",
            {"text": {"path": "/private/path"}},
        )


def test_standard_answer_must_match_the_pending_draft(client: TestClient):
    workspace_id = _setup(client)
    created = _create(client, workspace_id)
    current = _finish_candidate_discovery(client, workspace_id, created["id"])
    draft = current["question_drafts"][0]
    boundary = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/question-boundaries",
        json={
            "command_id": "boundary-for-standard-answer",
            "conversation_revision": current["revision"],
            "action": "confirm",
            "draft_ids": [draft["id"]],
        },
    )
    assert boundary.status_code == 200, boundary.text
    current = boundary.json()["conversation"]
    assert default_worker().run_once() is not None
    current = client.get(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}"
    ).json()["conversation"]
    pending = current["pending_question"]
    wrong = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/messages",
        json={
            "command_id": "wrong-standard-answer-target",
            "conversation_revision": current["revision"],
            "content": "这段答案不能归到另一道题。",
            "message_type": "standard_answer",
            "question_draft_id": "another-draft",
        },
    )
    assert wrong.status_code == 409
    assert wrong.json()["error"]["code"] == "STANDARD_ANSWER_NOT_REQUESTED"
    assert pending["question_draft_id"] == draft["id"]


def test_worker_failure_releases_authoring_conversation_for_retry(client: TestClient):
    workspace_id = _setup(client)
    created = _create(client, workspace_id)
    worker = default_worker()

    def fail_authoring(_job):
        raise RuntimeError("intentional test failure")

    worker.register("authoring_process", fail_authoring)
    failed = worker.run_once()
    assert failed is not None and failed.status.value == "failed"
    recovered = client.get(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}"
    )
    assert recovered.status_code == 200
    assert recovered.json()["conversation"]["status"] == "failed"
    assert recovered.json()["conversation"]["next_action"] == "retry_processing"


def test_concurrent_teacher_messages_have_one_winner(client: TestClient):
    workspace_id = _setup(client)
    created = _create(client, workspace_id)
    current = _finish_candidate_discovery(client, workspace_id, created["id"])

    def submit(content: str):
        parallel_client = TestClient(app)
        parallel_client.cookies.update(client.cookies)
        return parallel_client.post(
            f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/messages",
            json={
                "command_id": f"concurrent-{content[-1]}",
                "conversation_revision": current["revision"],
                "content": content,
            },
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(submit, ["第一条并发消息。", "第二条并发消息。"]))

    assert sorted(response.status_code for response in responses) == [202, 409]
    winner = next(response for response in responses if response.status_code == 202)
    assert winner.json()["conversation"]["status"] == "processing"


def test_boundary_mutation_cannot_change_a_non_candidate_draft(client: TestClient):
    workspace_id = _setup(client)
    created = _create(client, workspace_id, reference_answer_text="老师确认的标准答案。")
    current = _finish_candidate_discovery(client, workspace_id, created["id"])
    draft = current["question_drafts"][0]
    confirmed_boundary = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/question-boundaries",
        json={
            "command_id": "lock-boundary-first",
            "conversation_revision": current["revision"],
            "action": "confirm",
            "draft_ids": [draft["id"]],
        },
    )
    assert confirmed_boundary.status_code == 200, confirmed_boundary.text
    assert default_worker().run_once() is not None
    latest = client.get(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}"
    ).json()["conversation"]
    mutation = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}/question-boundaries",
        json={
            "command_id": "lock-boundary-second",
            "conversation_revision": latest["revision"],
            "action": "discard",
            "draft_ids": [draft["id"]],
        },
    )
    assert mutation.status_code == 409, mutation.text
    assert mutation.json()["error"]["code"] == "QUESTION_BOUNDARY_LOCKED"


def test_analyzer_with_no_usable_files_does_not_create_an_evidence_free_candidate(client: TestClient):
    workspace_id = _setup(client, "authoring-ignored")
    owner = auth_repository.find_by_username("authoring-ignored")
    assert owner is not None
    upload = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches",
        files={"files": ("evidence.md", b"some evidence", "text/markdown")},
        data={"title": "只有被忽略资料的批次"},
    )
    assert upload.status_code == 202, upload.text
    batch = upload.json()["batch"]
    file_id = batch["files"][0]["id"]
    file_record = ingestion_repository.get_file(file_id)
    assert file_record is not None
    ingestion_repository.update_disposition(
        batch_id=batch["id"],
        file_id=file_id,
        role="unknown",
        required=False,
        ignored=True,
        visibility="unconfirmed",
        rationale=None,
        confirmed_by=owner.id,
        expected_revision=batch["revision"],
    )
    created = _create(client, workspace_id, upload_batch_id=batch["id"])
    worker = default_worker()
    assert worker.run_once() is not None  # the upload batch analysis is queued first
    finished = worker.run_once()
    assert finished is not None and finished.status.value == "succeeded"
    current = client.get(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}"
    ).json()["conversation"]
    assert current["question_drafts"] == []
    assert current["next_action"] == "none"
    assert "没有可用于形成题目" in "".join(current["blocking_issues"])


def test_legacy_upload_roles_are_reopened_as_safe_authoring_roles(client: TestClient):
    workspace_id = _setup(client, "authoring-legacy")
    owner = auth_repository.find_by_username("authoring-legacy")
    assert owner is not None
    upload = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches",
        files={"files": ("legacy.md", b"legacy evidence", "text/markdown")},
        data={"title": "复用旧资料角色"},
    )
    assert upload.status_code == 202, upload.text
    batch = upload.json()["batch"]
    file_id = batch["files"][0]["id"]
    assert ingestion_repository.update_disposition(
        batch_id=batch["id"],
        file_id=file_id,
        role="runtime",
        required=False,
        ignored=False,
        visibility="runtime",
        rationale=None,
        confirmed_by=owner.id,
        expected_revision=batch["revision"],
    )
    created = _create(client, workspace_id, upload_batch_id=batch["id"])
    worker = default_worker()
    assert worker.run_once() is not None
    assert worker.run_once() is not None
    current = client.get(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{created['id']}"
    ).json()["conversation"]
    assert current["question_drafts"][0]["materials"][0]["role"] == "fact"


def test_safe_stream_events_keep_a_bounded_replay_window(client: TestClient):
    workspace_id = _setup(client)
    created = _create(client, workspace_id)
    for count in range(520):
        authoring_repository.append_event(
            created["id"],
            "action_summary",
            {"label": "读取资料", "count": count + 1},
        )
    events = authoring_repository.list_events(created["id"], after=0, limit=200)
    assert len(events) == 200
    assert events[0].sequence == 21
    assert authoring_repository.latest_event_sequence(created["id"]) == 520
