"""Rubric generation: fake/production contract, failure, retry, CAS races."""

from fastapi.testclient import TestClient

from app.lib.ai_runtime.adapters import FakeRubricGenerator
from app.lib.database import clear_business_data, session_scope
from app.lib.database.models import EvalQuestionRow
from app.main import app
from tests import helpers


def _upload_one(client: TestClient, *, task_prompt: str | None = None) -> str:
    helpers.register_admin(client)
    scene = helpers.create_scene(client)
    credential = helpers.issue_credential(client, scene["id"])
    case = helpers.make_case("case-rubric")
    if task_prompt:
        case["task_prompt"] = task_prompt
    response = helpers.upload_batch(client, credential["token"], helpers.make_batch("cmd-rubric", [case]))
    assert response.status_code == 201, response.text
    return response.json()["cases"][0]["question_id"]


def test_generation_produces_two_field_criteria_only() -> None:
    clear_business_data()
    with TestClient(app) as client:
        question_id = _upload_one(client)
        helpers.run_worker_until_idle()
        detail = client.get(f"/api/questions/{question_id}").json()
        assert detail["status"] == "pending_review"
        assert detail["next_action"] == "review_and_publish"
        assert detail["criteria"], "generated criteria must not be empty"
        for item in detail["criteria"]:
            assert set(item.keys()) == {"id", "criterion", "pass_score"}
            assert 0 <= item["pass_score"] <= 10
            # Vague isolated labels are not allowed through the contract.
            assert item["criterion"].strip() not in {"准确性", "创新性", "完整性"}
        assert detail["last_error"] is None


def test_generation_failure_marks_question_and_supports_retry() -> None:
    clear_business_data()
    with TestClient(app) as client:
        question_id = _upload_one(client, task_prompt=f"{FakeRubricGenerator.FAIL_MARKER} 生成失败的题目。")
        helpers.run_worker_until_idle()
        detail = client.get(f"/api/questions/{question_id}").json()
        assert detail["status"] == "generation_failed"
        assert detail["next_action"] == "retry_generation"
        assert detail["last_error"]["code"] == "AI_CALL_FAILED"
        assert detail["criteria"] is None

        # Retry is only available for failed questions.
        retry = client.post(
            f"/api/questions/{question_id}/generation-retry",
            json={"command_id": "retry-1", "content_revision": detail["content_revision"]},
        )
        assert retry.status_code == 200, retry.text
        detail = client.get(f"/api/questions/{question_id}").json()
        assert detail["status"] == "generating"

        # The prompt still carries the fail marker -> fails again deterministically.
        helpers.run_worker_until_idle()
        detail = client.get(f"/api/questions/{question_id}").json()
        assert detail["status"] == "generation_failed"

        # Remove the marker through save-and-regenerate; generation recovers.
        save = client.post(
            f"/api/questions/{question_id}/save-regenerate",
            json={
                "command_id": "fix-prompt",
                "content_revision": detail["content_revision"],
                "task_prompt": "请把提供的新闻素材改写成正式新闻稿。",
            },
        )
        assert save.status_code == 200, save.text
        helpers.run_worker_until_idle()
        detail = client.get(f"/api/questions/{question_id}").json()
        assert detail["status"] == "pending_review"


def test_vague_ai_output_is_rejected_as_failure() -> None:
    clear_business_data()
    with TestClient(app) as client:
        question_id = _upload_one(client, task_prompt=f"{FakeRubricGenerator.VAGUE_MARKER} 空泛输出题目。")
        helpers.run_worker_until_idle()
        detail = client.get(f"/api/questions/{question_id}").json()
        assert detail["status"] == "generation_failed"
        assert detail["last_error"]["code"] == "AI_OUTPUT_INVALID"


def test_save_and_regenerate_invalidates_old_criteria() -> None:
    clear_business_data()
    with TestClient(app) as client:
        question_id = _upload_one(client)
        helpers.run_worker_until_idle()
        detail = client.get(f"/api/questions/{question_id}").json()
        assert detail["status"] == "pending_review"
        old_revision = detail["content_revision"]

        save = client.post(
            f"/api/questions/{question_id}/save-regenerate",
            json={
                "command_id": "edit-1",
                "content_revision": old_revision,
                "reference_answer": "老师更新后的标准答案。",
            },
        )
        assert save.status_code == 200, save.text
        detail = client.get(f"/api/questions/{question_id}").json()
        assert detail["status"] == "generating"
        assert detail["criteria"] is None, "old criteria must be invalidated immediately"
        assert detail["content_revision"] == old_revision + 1

        # Stale revision edit conflicts.
        stale = client.post(
            f"/api/questions/{question_id}/save-regenerate",
            json={"command_id": "edit-2", "content_revision": old_revision, "title": "旧版本"},
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "STALE_REVISION"

        helpers.run_worker_until_idle()
        assert client.get(f"/api/questions/{question_id}").json()["status"] == "pending_review"


def test_concurrent_stale_generation_cannot_overwrite_new_materials() -> None:
    """A job launched for revision N must not write criteria after revision N+1."""

    clear_business_data()
    with TestClient(app) as client:
        question_id = _upload_one(client)
        # Simulate: the job for revision 1 is still queued when the admin edits.
        detail = client.get(f"/api/questions/{question_id}").json()
        save = client.post(
            f"/api/questions/{question_id}/save-regenerate",
            json={
                "command_id": "race-edit",
                "content_revision": detail["content_revision"],
                "reference_answer": "竞态发生后的新标准答案。",
            },
        )
        assert save.status_code == 200

        # Now run all jobs: the stale revision-1 job must supersede, only the
        # revision-2 job may commit.
        helpers.run_worker_until_idle()
        detail = client.get(f"/api/questions/{question_id}").json()
        assert detail["status"] == "pending_review"
        assert detail["reference_answer"] == "竞态发生后的新标准答案。"

        from app.lib.operations import repository as operation_repository

        jobs = operation_repository.list_for_target("eval_question", question_id)
        statuses = sorted(job.status.value for job in jobs)
        assert statuses.count("succeeded") == 1
        assert "superseded" in statuses


def test_retry_same_command_is_idempotent_after_failure() -> None:
    clear_business_data()
    with TestClient(app) as client:
        question_id = _upload_one(client, task_prompt=f"{FakeRubricGenerator.FAIL_MARKER} 失败题目。")
        helpers.run_worker_until_idle()
        detail = client.get(f"/api/questions/{question_id}").json()
        retry_payload = {
            "command_id": "retry-same",
            "content_revision": detail["content_revision"],
        }
        first = client.post(f"/api/questions/{question_id}/generation-retry", json=retry_payload)
        assert first.status_code == 200
        helpers.run_worker_until_idle()
        detail = client.get(f"/api/questions/{question_id}").json()
        assert detail["status"] == "generation_failed"
        # Same command again must revive the failed job cleanly. Before the
        # fix, reviving reset attempts to 0 while historical attempt rows
        # remained, so the next claim hit the (job_id, attempt_number) unique
        # constraint and poisoned the whole worker queue.
        second = client.post(f"/api/questions/{question_id}/generation-retry", json=retry_payload)
        assert second.status_code == 200, second.text
        helpers.run_worker_until_idle()
        revived = client.get(f"/api/questions/{question_id}").json()
        # The prompt still carries the fail marker, so it fails again — but
        # it must reach a settled terminal state, not hang in generating.
        assert revived["status"] == "generation_failed", revived["status"]
        assert revived["next_action"] == "retry_generation"


def test_title_only_edit_does_not_regenerate() -> None:
    clear_business_data()
    with TestClient(app) as client:
        question_id = _upload_one(client)
        helpers.run_worker_until_idle()
        detail = client.get(f"/api/questions/{question_id}").json()
        rename = client.patch(
            f"/api/questions/{question_id}/title",
            json={
                "command_id": "rename-1",
                "content_revision": detail["content_revision"],
                "title": "只改标题",
            },
        )
        assert rename.status_code == 200, rename.text
        updated = client.get(f"/api/questions/{question_id}").json()
        assert updated["title"] == "只改标题"
        assert updated["content_revision"] == detail["content_revision"]
        assert updated["status"] == "pending_review"
        assert updated["criteria"] == detail["criteria"]
