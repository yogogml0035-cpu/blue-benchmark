from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.features.evaluation_sets.rubric_schemas import RubricContent
from app.features.human_scoring import service as human_scoring_service
from app.features.human_scoring.schemas import ScoreCreateRequest
from app.lib.ai_runtime import reset_adapters
from app.lib.database import clear_business_data
from app.lib.storage import LocalStorage
from app.main import app
from app.features.evaluation_sets import rubric_repository
from tests.test_rubric_publishing import _start_and_generate
from tests.test_question_revision_versioning import _publish_authored_question_in_workspace


@pytest.fixture(autouse=True)
def reset_state():
    clear_business_data()
    reset_adapters()
    yield
    reset_adapters()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _published_question(client: TestClient) -> tuple[str, str]:
    workspace_id, question_draft_id, generated = _start_and_generate(client)
    confirmed = client.post(
        f"/api/workspaces/{workspace_id}/authoring/rubrics/{generated['id']}/confirmation",
        json={
            "command_id": f"score-rubric-confirm-{uuid4().hex}",
            "rubric_revision": generated["revision"],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    published = client.post(
        f"/api/workspaces/{workspace_id}/authoring/rubrics/{generated['id']}/publish",
        json={
            "command_id": f"score-rubric-publish-{uuid4().hex}",
            "rubric_revision": confirmed.json()["rubric"]["revision"],
        },
    )
    assert published.status_code == 200, published.text
    revision_id = published.json()["rubric"]["published_revision_id"]
    assert revision_id
    assert rubric_repository.get_revision(revision_id) is not None
    return workspace_id, revision_id


def _create_submission(client: TestClient, workspace_id: str, revision_id: str) -> dict:
    response = client.post(
        f"/api/workspaces/{workspace_id}/question-revisions/{revision_id}/submissions",
        json={
            "command_id": f"submission-{uuid4().hex}",
            "content_text": "这是一份待评新闻稿，包含可以被老师逐项核对的事实。",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _score_payload(submission: dict, *, command_id: str, first_score: int = 50) -> dict:
    criteria = submission["question_revision"]["criteria"]
    return {
        "command_id": command_id,
        "items": [
            {
                "criterion_id": criteria[0]["id"],
                "score": first_score,
                "reason": "待评文本缺少一部分可以复核的事实。",
                "hard_fail_triggered": None,
            },
            {
                "criterion_id": criteria[1]["id"],
                "score": 40,
                "reason": None,
                "hard_fail_triggered": None,
            },
        ],
        "overall_reason": "整体交付可用，但事实部分需要补证。",
    }


def _score_payload_for_revision(
    submission: dict,
    revision_id: str,
    *,
    command_id: str,
    first_score: int = 50,
) -> dict:
    revision = submission["question_revisions"][revision_id]
    criteria = revision["criteria"]
    return {
        "command_id": command_id,
        "question_revision_id": revision_id,
        "items": [
            {
                "criterion_id": criteria[0]["id"],
                "score": first_score,
                "reason": "新版标准下仍有一处来源需要补充。",
                "hard_fail_triggered": None,
            },
            {
                "criterion_id": criteria[1]["id"],
                "score": criteria[1]["max_score"],
                "reason": None,
                "hard_fail_triggered": None,
            },
        ],
        "overall_reason": "按新版规则复核后，来源可追溯性仍需补充。",
    }


def test_pasted_submission_and_server_computed_score_are_recoverable(client: TestClient):
    workspace_id, revision_id = _published_question(client)
    submission = _create_submission(client, workspace_id, revision_id)
    body = submission["submission"]
    assert body["source"] == "paste"
    assert body["content_text"].startswith("这是一份待评新闻稿")
    assert "content_storage_key" not in body
    assert submission["question_revision"]["id"] == revision_id

    score_payload = _score_payload(submission, command_id=f"score-{uuid4().hex}")
    score_response = client.post(
        f"/api/workspaces/{workspace_id}/submissions/{body['id']}/scores",
        json=score_payload,
    )
    assert score_response.status_code == 201, score_response.text
    score = score_response.json()["score"]
    assert score["total_score"] == 90
    assert score["critical_passed"] is True
    assert score["passed"] is True
    assert score["items"][0]["critical_passed"] is True

    root_after_existing = client.post(
        f"/api/workspaces/{workspace_id}/submissions/{body['id']}/scores",
        json=_score_payload(submission, command_id=f"second-root-{uuid4().hex}"),
    )
    assert root_after_existing.status_code == 409, root_after_existing.text
    assert root_after_existing.json()["error"]["code"] == "PARENT_SCORE_REQUIRED"

    recovered = client.get(f"/api/workspaces/{workspace_id}/submissions/{body['id']}")
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["submission"]["content_text"] == body["content_text"]
    assert [item["id"] for item in recovered.json()["scores"]] == [score["id"]]


def test_submission_and_score_commands_are_idempotent_but_conflicts_fail(client: TestClient):
    workspace_id, revision_id = _published_question(client)
    command_id = f"stable-submission-{uuid4().hex}"
    path = f"/api/workspaces/{workspace_id}/question-revisions/{revision_id}/submissions"
    first = client.post(path, json={"command_id": command_id, "content_text": "同一份答卷。"})
    assert first.status_code == 201, first.text
    repeated = client.post(path, json={"command_id": command_id, "content_text": "同一份答卷。"})
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["submission"]["id"] == first.json()["submission"]["id"]
    conflict = client.post(path, json={"command_id": command_id, "content_text": "另一份答卷。"})
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "COMMAND_ID_REUSED"

    submission = first.json()
    score_path = f"/api/workspaces/{workspace_id}/submissions/{submission['submission']['id']}/scores"
    score_payload = _score_payload(submission, command_id=f"stable-score-{uuid4().hex}")
    score = client.post(score_path, json=score_payload)
    assert score.status_code == 201, score.text
    repeated_score = client.post(score_path, json=score_payload)
    assert repeated_score.status_code == 201, repeated_score.text
    assert repeated_score.json()["score"]["id"] == score.json()["score"]["id"]
    score_conflict_payload = _score_payload(
        submission,
        command_id=score_payload["command_id"],
        first_score=49,
    )
    score_conflict = client.post(score_path, json=score_conflict_payload)
    assert score_conflict.status_code == 409, score_conflict.text
    assert score_conflict.json()["error"]["code"] == "COMMAND_ID_REUSED"


def test_same_submission_command_concurrently_creates_one_ready_object(client: TestClient):
    workspace_id, revision_id = _published_question(client)
    path = f"/api/workspaces/{workspace_id}/question-revisions/{revision_id}/submissions"
    payload = {"command_id": f"concurrent-{uuid4().hex}", "content_text": "并发提交仍然只能保留一份答卷。"}

    def submit_once():
        with TestClient(app) as local_client:
            local_client.cookies.update(client.cookies)
            return local_client.post(path, json=payload)

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _index: submit_once(), range(2)))
    assert [response.status_code for response in responses] == [201, 201]
    assert len({response.json()["submission"]["id"] for response in responses}) == 1
    assert human_scoring_service.repository.get_submission_by_command(workspace_id, payload["command_id"])


def test_pasted_utf8_limit_is_measured_in_bytes(client: TestClient):
    workspace_id, revision_id = _published_question(client)
    response = client.post(
        f"/api/workspaces/{workspace_id}/question-revisions/{revision_id}/submissions",
        json={
            "command_id": f"multibyte-limit-{uuid4().hex}",
            "content_text": "中" * 400_000,
        },
    )
    assert response.status_code == 413, response.text
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_score_requires_exact_criteria_and_reason_for_anchor_or_critical_failure(client: TestClient):
    workspace_id, revision_id = _published_question(client)
    submission = _create_submission(client, workspace_id, revision_id)
    score_path = f"/api/workspaces/{workspace_id}/submissions/{submission['submission']['id']}/scores"
    criteria = submission["question_revision"]["criteria"]

    missing = client.post(
        score_path,
        json={
            "command_id": f"missing-{uuid4().hex}",
            "items": [{"criterion_id": criteria[0]["id"], "score": 50}],
        },
    )
    assert missing.status_code == 422, missing.text
    assert missing.json()["error"]["code"] == "SCORE_ITEMS_INCOMPLETE"

    no_reason = client.post(
        score_path,
        json={
            "command_id": f"no-reason-{uuid4().hex}",
            "items": [
                {"criterion_id": criteria[0]["id"], "score": 30},
                {"criterion_id": criteria[1]["id"], "score": 40},
            ],
        },
    )
    assert no_reason.status_code == 422, no_reason.text
    assert no_reason.json()["error"]["code"] == "SCORE_REASON_REQUIRED"

    forged = client.post(
        score_path,
        json={**_score_payload(submission, command_id=f"forged-{uuid4().hex}"), "total_score": 100, "passed": True},
    )
    assert forged.status_code == 422, forged.text
    assert forged.json()["error"]["code"] == "VALIDATION_ERROR"

    over_max = client.post(
        score_path,
        json={
            "command_id": f"over-max-{uuid4().hex}",
            "items": [
                {
                    "criterion_id": criteria[0]["id"],
                    "score": 61,
                    "reason": "超过评分项满分。",
                },
                {"criterion_id": criteria[1]["id"], "score": 40},
            ],
        },
    )
    assert over_max.status_code == 422, over_max.text
    assert over_max.json()["error"]["code"] == "SCORE_OUT_OF_RANGE"


def test_hard_fail_decision_is_server_validated_and_derived():
    rubric = RubricContent(
        pass_threshold=60,
        criteria=[
            {
                "id": "fact_gate",
                "name": "事实门槛",
                "purpose": "检查事实是否可以复核。",
                "max_score": 100,
                "award_points": ["关键事实可以复核。"],
                "critical": True,
                "critical_mode": "hard_fail",
                "hard_fail_conditions": ["出现无法核实的核心事实。"],
                "reference_expected_score": 100,
                "reference_score_reason": "标准答案中的事实均可复核。",
            }
        ],
    )
    with pytest.raises(Exception):
        human_scoring_service._validated_score_items(
            rubric,
            ScoreCreateRequest(
                command_id="hard-fail-missing",
                items=[{"criterion_id": "fact_gate", "score": 100}],
            ),
        )
    items, total, critical_passed, passed = human_scoring_service._validated_score_items(
        rubric,
        ScoreCreateRequest(
            command_id="hard-fail-hit",
            items=[
                {
                    "criterion_id": "fact_gate",
                    "score": 100,
                    "hard_fail_triggered": True,
                    "reason": "出现无法核实的核心事实。",
                }
            ],
        ),
    )
    assert items[0]["critical_passed"] is False
    assert (total, critical_passed, passed) == (100, False, False)


def test_upload_accepts_one_utf8_markdown_and_rejects_type_encoding_and_size(client: TestClient):
    workspace_id, revision_id = _published_question(client)
    path = f"/api/workspaces/{workspace_id}/question-revisions/{revision_id}/submissions/upload"
    valid = client.post(
        path,
        data={"command_id": f"upload-{uuid4().hex}"},
        files={"file": ("answer.md", "# 结论\n\n正文。".encode("utf-8"), "text/markdown")},
    )
    assert valid.status_code == 201, valid.text
    assert valid.json()["submission"]["source"] == "file"
    assert valid.json()["submission"]["original_name"] == "answer.md"

    multiple = client.post(
        path,
        data={"command_id": f"multiple-{uuid4().hex}"},
        files=[
            ("file", ("one.md", "一份。".encode("utf-8"), "text/markdown")),
            ("file", ("two.md", "另一份。".encode("utf-8"), "text/markdown")),
        ],
    )
    assert multiple.status_code == 422, multiple.text

    bad_type = client.post(
        path,
        data={"command_id": f"bad-type-{uuid4().hex}"},
        files={"file": ("answer.pdf", b"%PDF-1.7", "application/pdf")},
    )
    assert bad_type.status_code == 415, bad_type.text

    bad_encoding = client.post(
        path,
        data={"command_id": f"bad-encoding-{uuid4().hex}"},
        files={"file": ("answer.txt", b"\xff\xfeinvalid", "text/plain")},
    )
    assert bad_encoding.status_code == 422, bad_encoding.text
    mime_mismatch = client.post(
        path,
        data={"command_id": f"mime-mismatch-{uuid4().hex}"},
        files={"file": ("answer.md", "正文".encode("utf-8"), "application/pdf")},
    )
    assert mime_mismatch.status_code == 415, mime_mismatch.text
    too_large = client.post(
        path,
        data={"command_id": f"too-large-{uuid4().hex}"},
        files={"file": ("answer.txt", b"a" * (1 * 1024 * 1024 + 1), "text/plain")},
    )
    assert too_large.status_code == 413, too_large.text


def test_rescore_appends_history_and_cannot_cross_submission(client: TestClient):
    workspace_id, revision_id = _published_question(client)
    first_submission = _create_submission(client, workspace_id, revision_id)
    second_submission = _create_submission(client, workspace_id, revision_id)
    first_path = f"/api/workspaces/{workspace_id}/submissions/{first_submission['submission']['id']}/scores"
    first = client.post(
        first_path,
        json=_score_payload(first_submission, command_id=f"first-{uuid4().hex}"),
    )
    assert first.status_code == 201, first.text
    first_score = first.json()["score"]
    rescore_payload = _score_payload(
        first_submission,
        command_id=f"rescore-{uuid4().hex}",
        first_score=45,
    )
    rescore_payload["parent_score_id"] = first_score["id"]
    rescore = client.post(first_path, json=rescore_payload)
    assert rescore.status_code == 201, rescore.text
    rescore_score = rescore.json()["score"]
    assert rescore_score["id"] != first_score["id"]
    assert rescore_score["parent_score_id"] == first_score["id"]

    second_path = f"/api/workspaces/{workspace_id}/submissions/{second_submission['submission']['id']}/scores"
    cross = _score_payload(
        second_submission,
        command_id=f"cross-{uuid4().hex}",
    )
    cross["parent_score_id"] = first_score["id"]
    cross_response = client.post(second_path, json=cross)
    assert cross_response.status_code == 422, cross_response.text
    assert cross_response.json()["error"]["code"] == "INVALID_PARENT_SCORE"
    unknown_parent = _score_payload(second_submission, command_id=f"unknown-parent-{uuid4().hex}")
    unknown_parent["parent_score_id"] = str(uuid4())
    unknown_response = client.post(second_path, json=unknown_parent)
    assert unknown_response.status_code == 422, unknown_response.text
    assert unknown_response.json()["error"]["code"] == "INVALID_PARENT_SCORE"

    history = client.get(f"{first_path}")
    assert history.status_code == 200, history.text
    assert [item["id"] for item in history.json()["scores"]] == [first_score["id"], rescore_score["id"]]


def test_concurrent_rescores_claim_one_latest_parent(client: TestClient):
    workspace_id, revision_id = _published_question(client)
    submission = _create_submission(client, workspace_id, revision_id)
    score_path = f"/api/workspaces/{workspace_id}/submissions/{submission['submission']['id']}/scores"
    first = client.post(
        score_path,
        json=_score_payload(submission, command_id=f"concurrent-parent-first-{uuid4().hex}"),
    )
    assert first.status_code == 201, first.text
    parent_id = first.json()["score"]["id"]

    payloads = []
    for index in range(2):
        payload = _score_payload(
            submission,
            command_id=f"concurrent-parent-rescore-{index}-{uuid4().hex}",
            first_score=45 + index,
        )
        payload["parent_score_id"] = parent_id
        payloads.append(payload)

    def submit_once(payload: dict):
        with TestClient(app) as local_client:
            local_client.cookies.update(client.cookies)
            return local_client.post(score_path, json=payload)

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(submit_once, payloads))

    assert sorted(response.status_code for response in responses) == [201, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json()["error"]["code"] == "PARENT_SCORE_STALE"
    history = client.get(score_path)
    assert history.status_code == 200, history.text
    assert len(history.json()["scores"]) == 2


def test_rescore_uses_same_question_new_revision_and_preserves_each_revision_view(client: TestClient):
    workspace_id, revision_id = _published_question(client)
    submission = _create_submission(client, workspace_id, revision_id)
    first_path = f"/api/workspaces/{workspace_id}/submissions/{submission['submission']['id']}/scores"
    first = client.post(
        first_path,
        json=_score_payload(submission, command_id=f"revision-first-{uuid4().hex}"),
    )
    assert first.status_code == 201, first.text
    first_score = first.json()["score"]

    original = rubric_repository.get_revision(revision_id)
    assert original is not None
    derived = client.post(
        f"/api/workspaces/{workspace_id}/authoring/question-drafts/{original.question_draft_id}/revisions/{revision_id}/derive-draft",
        json={"command_id": f"revision-derive-{uuid4().hex}"},
    )
    assert derived.status_code == 200, derived.text
    rubric_body = derived.json()["rubric"]
    changed_rubric = RubricContent.model_validate(rubric_body["rubric"]).model_dump(mode="json")
    changed_rubric["criteria"][0]["id"] = "source_traceability"
    changed_rubric["criteria"][0]["name"] = "来源可追溯性"
    changed_rubric["criteria"][1]["id"] = "deliverable_quality_v2"
    patched = client.patch(
        f"/api/workspaces/{workspace_id}/authoring/rubrics/{rubric_body['id']}",
        json={
            "command_id": f"revision-patch-{uuid4().hex}",
            "rubric_revision": rubric_body["revision"],
            "rubric": changed_rubric,
        },
    )
    assert patched.status_code == 200, patched.text
    confirmed = client.post(
        f"/api/workspaces/{workspace_id}/authoring/rubrics/{rubric_body['id']}/confirmation",
        json={
            "command_id": f"revision-confirm-{uuid4().hex}",
            "rubric_revision": patched.json()["rubric"]["revision"],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    published = client.post(
        f"/api/workspaces/{workspace_id}/authoring/rubrics/{rubric_body['id']}/publish",
        json={
            "command_id": f"revision-publish-{uuid4().hex}",
            "rubric_revision": confirmed.json()["rubric"]["revision"],
        },
    )
    assert published.status_code == 200, published.text
    next_revision_id = published.json()["rubric"]["published_revision_id"]

    refreshed = client.get(f"/api/workspaces/{workspace_id}/submissions/{submission['submission']['id']}")
    assert refreshed.status_code == 200, refreshed.text
    refreshed_submission = refreshed.json()
    assert set(refreshed_submission["question_revisions"]) == {revision_id, next_revision_id}
    next_payload = _score_payload_for_revision(
        refreshed_submission,
        next_revision_id,
        command_id=f"revision-rescore-{uuid4().hex}",
        first_score=45,
    )
    next_payload["parent_score_id"] = first_score["id"]
    rescored = client.post(first_path, json=next_payload)
    assert rescored.status_code == 201, rescored.text
    next_score = rescored.json()["score"]
    assert next_score["question_revision_id"] == next_revision_id
    assert next_score["parent_score_id"] == first_score["id"]
    assert next_score["total_score"] == 85

    recovered = client.get(f"/api/workspaces/{workspace_id}/submissions/{submission['submission']['id']}")
    assert recovered.status_code == 200, recovered.text
    body = recovered.json()
    assert body["submission"]["content_text"] == submission["submission"]["content_text"]
    assert body["question_revision"]["id"] == revision_id
    assert [item["question_revision_id"] for item in body["scores"]] == [revision_id, next_revision_id]
    assert body["question_revisions"][next_revision_id]["criteria"][0]["id"] == "source_traceability"
    assert body["question_revisions"][revision_id]["criteria"][0]["id"] != "source_traceability"

    repeated = client.post(first_path, json=next_payload)
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["score"]["id"] == next_score["id"]


def test_rescore_rejects_cross_question_and_first_score_new_revision(client: TestClient):
    workspace_id, revision_id = _published_question(client)
    submission = _create_submission(client, workspace_id, revision_id)
    other_question_draft_id, other_revision_id, _ = _publish_authored_question_in_workspace(client, workspace_id)
    assert other_question_draft_id
    score_path = f"/api/workspaces/{workspace_id}/submissions/{submission['submission']['id']}/scores"
    payload = _score_payload(submission, command_id=f"cross-question-{uuid4().hex}")
    payload["question_revision_id"] = other_revision_id
    response = client.post(score_path, json=payload)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "SCORE_REVISION_MISMATCH"
    assert human_scoring_service.repository.list_scores(submission["submission"]["id"]) == []

    first_revision_payload = _score_payload(submission, command_id=f"first-new-revision-{uuid4().hex}")
    first_revision_payload["question_revision_id"] = str(uuid4())
    unknown = client.post(score_path, json=first_revision_payload)
    assert unknown.status_code == 404, unknown.text

    other_client = TestClient(app)
    _other_workspace_id, other_revision_id = _published_question(other_client)
    cross_workspace_payload = _score_payload(
        submission,
        command_id=f"cross-workspace-{uuid4().hex}",
    )
    cross_workspace_payload["question_revision_id"] = other_revision_id
    cross_workspace = client.post(score_path, json=cross_workspace_payload)
    assert cross_workspace.status_code == 403, cross_workspace.text
    assert cross_workspace.json()["error"]["code"] == "FORBIDDEN"
    assert human_scoring_service.repository.list_scores(submission["submission"]["id"]) == []


def test_owner_isolation_and_storage_tampering_fail_closed(client: TestClient):
    workspace_id, revision_id = _published_question(client)
    submission = _create_submission(client, workspace_id, revision_id)
    submission_id = submission["submission"]["id"]

    other_username = f"other-{uuid4().hex[:10]}"
    other = client.post(
        "/api/auth/register",
        json={"username": other_username, "email": f"{other_username}@example.com", "password": "password123"},
    )
    assert other.status_code == 409, other.text

    other_client = TestClient(app)
    registered = other_client.post(
        "/api/auth/register",
        json={"username": other_username, "email": f"{other_username}@example.com", "password": "password123"},
    )
    assert registered.status_code == 201, registered.text
    assert other_client.get(f"/api/workspaces/{workspace_id}/submissions/{submission_id}").status_code == 403
    forbidden_upload = other_client.post(
        f"/api/workspaces/{workspace_id}/question-revisions/{revision_id}/submissions/upload",
        data={"command_id": f"forbidden-{uuid4().hex}"},
        files={"file": ("answer.pdf", b"not inspected", "application/pdf")},
    )
    assert forbidden_upload.status_code == 403, forbidden_upload.text

    record = human_scoring_service.repository.get_submission(submission_id)
    assert record is not None
    LocalStorage().write_bytes(record.content_storage_key, b"tampered secret body")
    tampered = client.get(f"/api/workspaces/{workspace_id}/submissions/{submission_id}")
    assert tampered.status_code == 500, tampered.text
    assert "tampered secret body" not in tampered.text
    score_after_tamper = client.post(
        f"/api/workspaces/{workspace_id}/submissions/{submission_id}/scores",
        json=_score_payload(submission, command_id=f"tampered-score-{uuid4().hex}"),
    )
    assert score_after_tamper.status_code == 500, score_after_tamper.text
    assert human_scoring_service.repository.list_scores(submission_id) == []


def test_database_write_failure_cleans_published_submission_objects(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    workspace_id, revision_id = _published_question(client)
    path = f"/api/workspaces/{workspace_id}/question-revisions/{revision_id}/submissions"
    storage_root = human_scoring_service.LocalStorage().root
    before = {item.relative_to(storage_root) for item in storage_root.rglob("*") if item.is_file()}

    def fail_add(_record):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(human_scoring_service.repository, "add_submission", fail_add)
    failure_client = TestClient(app, raise_server_exceptions=False)
    failure_client.cookies.update(client.cookies)
    response = failure_client.post(
        path,
        json={"command_id": f"db-failure-{uuid4().hex}", "content_text": "不会留下孤儿文件。"},
    )
    assert response.status_code == 500, response.text
    assert "database unavailable" not in response.text
    after = {item.relative_to(storage_root) for item in storage_root.rglob("*") if item.is_file()}
    assert after == before
