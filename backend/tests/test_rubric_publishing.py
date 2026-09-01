from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.features.case_builder import authoring_repository
from app.features.evaluation_sets import rubric_repository
from app.features.evaluation_sets.rubric_schemas import RubricContent
from app.lib.ai_runtime import get_adapters, reset_adapters, set_adapters
from app.lib.database import clear_business_data
from app.lib.operations import repository as operation_repository
from app.lib.operations.worker import default_worker
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


def _confirmed_question(client: TestClient) -> tuple[str, str, str, int]:
    username = f"rubric-{uuid4().hex[:8]}"
    registered = client.post(
        "/api/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "password123"},
    )
    assert registered.status_code == 201, registered.text
    workspace_id = client.post("/api/workspaces", json={"name": "规则场景"}).json()["workspace"]["id"]
    created = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations",
        json={
            "command_id": "rubric-authoring-create",
            "title": "规则题",
            "task_instruction": "请根据确认资料形成一份事实准确的结果。",
            "reference_answer_text": "老师明确认可的终版结果。",
        },
    )
    assert created.status_code == 202, created.text
    conversation_id = created.json()["conversation"]["id"]
    assert default_worker().run_once() is not None
    current = client.get(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation_id}"
    ).json()["conversation"]
    draft = current["question_drafts"][0]
    boundary = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation_id}/question-boundaries",
        json={
            "command_id": "rubric-confirm-boundary",
            "conversation_revision": current["revision"],
            "action": "confirm",
            "draft_ids": [draft["id"]],
        },
    )
    assert boundary.status_code == 200, boundary.text
    assert default_worker().run_once() is not None
    current = client.get(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation_id}"
    ).json()["conversation"]
    draft = current["question_drafts"][0]
    confirmed = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation_id}/question-drafts/{draft['id']}/input-answer-confirmation",
        json={"command_id": "rubric-confirm-input", "draft_revision": draft["revision"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["conversation"]["status"] == "confirmed"
    confirmed_draft = next(
        item
        for item in confirmed.json()["conversation"]["question_drafts"]
        if item["id"] == draft["id"]
    )
    return workspace_id, draft["id"], conversation_id, confirmed_draft["confirmed_revision"]


def _start_and_generate(client: TestClient) -> tuple[str, str, dict]:
    workspace_id, question_draft_id, _conversation_id, question_revision = _confirmed_question(client)
    started = client.post(
        f"/api/workspaces/{workspace_id}/authoring/question-drafts/{question_draft_id}/rubric",
        json={"command_id": "rubric-generate", "question_revision": question_revision},
    )
    assert started.status_code == 202, started.text
    rubric_id = started.json()["rubric"]["id"]
    assert default_worker().run_once() is not None
    generated = client.get(f"/api/workspaces/{workspace_id}/authoring/rubrics/{rubric_id}")
    assert generated.status_code == 200, generated.text
    body = generated.json()["rubric"]
    assert body["status"] == "review_ready"
    assert body["reference_total_score"] == 98
    assert body["reference_critical_passed"] is True
    assert body["reference_passed"] is True
    return workspace_id, question_draft_id, body


def test_rubric_content_rejects_invalid_score_and_similarity_rules():
    with pytest.raises(ValueError, match="sum"):
        RubricContent(
            criteria=[
                {
                    "id": "one",
                    "name": "事实准确性",
                    "purpose": "保证事实正确。",
                    "max_score": 99,
                    "award_points": ["事实可复核。"],
                    "reference_expected_score": 99,
                    "reference_score_reason": "可以通过。",
                }
            ]
        )
    with pytest.raises(ValueError, match="unique"):
        RubricContent(
            criteria=[
                {
                    "id": "same",
                    "name": "事实准确性",
                    "purpose": "保证事实正确。",
                    "max_score": 50,
                    "award_points": ["事实可复核。"],
                    "reference_expected_score": 50,
                    "reference_score_reason": "可以通过。",
                },
                {
                    "id": "same",
                    "name": "交付完整性",
                    "purpose": "保证交付完整。",
                    "max_score": 50,
                    "award_points": ["覆盖任务要求。"],
                    "reference_expected_score": 50,
                    "reference_score_reason": "可以通过。",
                },
            ]
        )
    with pytest.raises(ValueError, match="hard-fail|hard_fail"):
        RubricContent(
            criteria=[
                {
                    "id": "critical",
                    "name": "事实准确性",
                    "purpose": "保证事实正确。",
                    "max_score": 100,
                    "award_points": ["事实可复核。"],
                    "critical": True,
                    "critical_mode": "hard_fail",
                    "critical_min_score": 40,
                    "hard_fail_conditions": ["出现无法核实的事实。"],
                    "reference_expected_score": 100,
                    "reference_score_reason": "可以通过。",
                }
            ]
        )
    with pytest.raises(ValueError, match="similarity|相似"):
        RubricContent(
            criteria=[
                {
                    "id": "similarity",
                    "name": "文本相似度",
                    "purpose": "判断输出是否相似。",
                    "max_score": 100,
                    "award_points": ["与标准答案措辞一致。"],
                    "reference_expected_score": 100,
                    "reference_score_reason": "可以通过。",
                }
            ]
        )


def test_get_before_generation_is_a_readable_empty_state_not_a_resource_error(client: TestClient):
    workspace_id, question_draft_id, _conversation_id, _question_revision = _confirmed_question(client)
    response = client.get(
        f"/api/workspaces/{workspace_id}/authoring/question-drafts/{question_draft_id}/rubric"
    )
    assert response.status_code == 200, response.text
    body = response.json()["rubric"]
    assert body["status"] == "not_started"
    assert body["next_action"] == "start_rubric"
    assert body["rubric"] is None
    assert rubric_repository.get_by_question(question_draft_id) is None


def test_generate_edit_confirm_publish_is_idempotent_and_immutable(client: TestClient):
    workspace_id, question_draft_id, generated = _start_and_generate(client)
    rubric_id = generated["id"]
    confirmed = client.post(
        f"/api/workspaces/{workspace_id}/authoring/rubrics/{rubric_id}/confirmation",
        json={"command_id": "rubric-confirm", "rubric_revision": generated["revision"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    confirmed_body = confirmed.json()["rubric"]
    published = client.post(
        f"/api/workspaces/{workspace_id}/authoring/rubrics/{rubric_id}/publish",
        json={"command_id": "rubric-publish", "rubric_revision": confirmed_body["revision"]},
    )
    assert published.status_code == 200, published.text
    published_body = published.json()["rubric"]
    revision_id = published_body["published_revision_id"]
    repeated = client.post(
        f"/api/workspaces/{workspace_id}/authoring/rubrics/{rubric_id}/publish",
        json={"command_id": "rubric-publish", "rubric_revision": confirmed_body["revision"]},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["rubric"]["published_revision_id"] == revision_id
    blocked_edit = client.patch(
        f"/api/workspaces/{workspace_id}/authoring/rubrics/{rubric_id}",
        json={
            "command_id": "rubric-edit-after-publish",
            "rubric_revision": published_body["revision"],
            "rubric": published_body["rubric"],
        },
    )
    assert blocked_edit.status_code == 409
    revisions = client.get(
        f"/api/workspaces/{workspace_id}/authoring/question-drafts/{question_draft_id}/revisions"
    )
    assert revisions.status_code == 200
    assert [item["id"] for item in revisions.json()["revisions"]] == [revision_id]
    derived = client.post(
        f"/api/workspaces/{workspace_id}/authoring/question-drafts/{question_draft_id}/revisions/{revision_id}/derive-draft",
        json={"command_id": "rubric-derive"},
    )
    assert derived.status_code == 200, derived.text
    assert derived.json()["rubric"]["status"] == "review_ready"


def test_reference_answer_failure_blocks_confirmation_and_publish(client: TestClient):
    workspace_id, _question_draft_id, generated = _start_and_generate(client)
    rubric = generated["rubric"]
    rubric["criteria"][0]["reference_expected_score"] = 1
    rubric["criteria"][1]["reference_expected_score"] = 1
    patched = client.patch(
        f"/api/workspaces/{workspace_id}/authoring/rubrics/{generated['id']}",
        json={"command_id": "rubric-low-reference", "rubric_revision": generated["revision"], "rubric": rubric},
    )
    assert patched.status_code == 200, patched.text
    blocked = client.post(
        f"/api/workspaces/{workspace_id}/authoring/rubrics/{generated['id']}/confirmation",
        json={"command_id": "rubric-low-confirm", "rubric_revision": patched.json()["rubric"]["revision"]},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "REFERENCE_RUBRIC_FAILED"


def test_upstream_change_invalidates_rubric_and_cross_workspace_is_forbidden(client: TestClient):
    workspace_id, question_draft_id, generated = _start_and_generate(client)
    conversation = authoring_repository.get_conversation_by_draft(question_draft_id)
    assert conversation is not None
    authoring = client.get(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation.id}"
    )
    assert authoring.status_code == 200
    draft = next(item for item in authoring.json()["conversation"]["question_drafts"] if item["id"] == question_draft_id)
    changed = client.patch(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation.id}/question-drafts/{question_draft_id}/input-answer",
        json={
            "command_id": "rubric-upstream-change",
            "draft_revision": draft["revision"],
            "input": {**draft["input"], "task_instruction": "请根据更新后的确认要求形成结果。"},
            "reference_answer_text": "老师明确认可的更新终版结果。",
        },
    )
    assert changed.status_code == 200, changed.text
    stale = client.get(f"/api/workspaces/{workspace_id}/authoring/rubrics/{generated['id']}")
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "QUESTION_NOT_CONFIRMED"
    # The rubric source remains scoped to the owning workspace.
    other_username = f"other-{uuid4().hex[:8]}"
    other = TestClient(app)
    assert other.post(
        "/api/auth/register",
        json={"username": other_username, "email": f"{other_username}@example.com", "password": "password123"},
    ).status_code == 201
    forbidden = other.get(f"/api/workspaces/{workspace_id}/authoring/rubrics/{generated['id']}")
    assert forbidden.status_code == 403
    assert authoring_repository.get_conversation_by_draft(question_draft_id) is not None


def test_projection_pending_retry_reuses_saved_result_without_another_model_call(client: TestClient, monkeypatch):
    workspace_id, question_draft_id, _conversation_id, question_revision = _confirmed_question(client)
    started = client.post(
        f"/api/workspaces/{workspace_id}/authoring/question-drafts/{question_draft_id}/rubric",
        json={"command_id": "rubric-pending-start", "question_revision": question_revision},
    )
    assert started.status_code == 202

    original_commit = rubric_repository.commit_worker_projection

    def fail_projection(*_args, **_kwargs):
        raise RuntimeError("synthetic projection failure")

    monkeypatch.setattr(rubric_repository, "commit_worker_projection", fail_projection)
    first = default_worker().run_once()
    assert first is not None and first.status.value == "projection_pending"
    rubric_id = started.json()["rubric"]["id"]
    pending = rubric_repository.get_draft(rubric_id)
    assert pending is not None
    jobs = operation_repository.list_for_target("rubric_draft", rubric_id)
    assert jobs and jobs[0].kind == "rubric_process"
    assert isinstance((jobs[0].result or {}).get("__rubric_projection"), dict)

    monkeypatch.setattr(rubric_repository, "commit_worker_projection", original_commit)
    calls = 0

    class NoModelCall:
        def generate(self, *_args, **_kwargs):
            nonlocal calls
            calls += 1
            raise AssertionError("projection retry must not invoke the model")

    current_adapters = get_adapters()
    set_adapters(replace(current_adapters, rubric_cocreator=NoModelCall()))
    retry = client.post(
        f"/api/workspaces/{workspace_id}/authoring/question-drafts/{question_draft_id}/rubric",
        json={"command_id": "rubric-pending-retry", "question_revision": question_revision},
    )
    assert retry.status_code == 202, retry.text
    retry_jobs = operation_repository.list_for_target("rubric_draft", rubric_id)
    assert retry_jobs[0].kind == "rubric_reproject"
    completed = default_worker().run_once()
    assert completed is not None and completed.status.value == "succeeded"
    assert calls == 0
    recovered = client.get(f"/api/workspaces/{workspace_id}/authoring/rubrics/{rubric_id}")
    assert recovered.status_code == 200
    assert recovered.json()["rubric"]["status"] == "review_ready"
