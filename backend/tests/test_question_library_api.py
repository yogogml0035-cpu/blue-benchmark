"""Library queries, criteria editing, publication gates, overwrite semantics."""

from fastapi.testclient import TestClient

from app.lib.database import clear_business_data
from app.main import app
from tests import helpers


def _setup_with_generated_question(client: TestClient) -> str:
    helpers.register_admin(client)
    scene = helpers.create_scene(client)
    credential = helpers.issue_credential(client, scene["id"])
    response = helpers.upload_batch(
        client, credential["token"], helpers.make_batch("cmd-lib", [helpers.make_case("case-lib")])
    )
    assert response.status_code == 201, response.text
    question_id = response.json()["cases"][0]["question_id"]
    helpers.run_worker_until_idle()
    return question_id


def test_library_filters_by_status_and_scene() -> None:
    clear_business_data()
    with TestClient(app) as client:
        question_id = _setup_with_generated_question(client)
        scene_id = client.get(f"/api/questions/{question_id}").json()["scene_id"]

        listing = client.get("/api/questions").json()
        assert listing["total"] == 1
        assert listing["items"][0]["scene_name"]

        published_only = client.get("/api/questions?status=published").json()
        assert published_only["total"] == 0

        pending = client.get("/api/questions?status=pending_review").json()
        assert pending["total"] == 1

        in_scene = client.get(f"/api/questions?scene_id={scene_id}").json()
        assert in_scene["total"] == 1

        missing_scene = client.get("/api/questions?scene_id=no-such-scene").json()
        assert missing_scene["total"] == 0


def test_publish_requires_valid_criteria_and_overwrite_on_edit() -> None:
    clear_business_data()
    with TestClient(app) as client:
        question_id = _setup_with_generated_question(client)
        detail = client.get(f"/api/questions/{question_id}").json()

        published = client.post(
            f"/api/questions/{question_id}/publication",
            json={"command_id": "publish-1", "content_revision": detail["content_revision"]},
        )
        assert published.status_code == 200, published.text
        body = published.json()
        assert body["status"] == "published"
        assert body["next_action"] == "published"
        assert body["published_at"] is not None

        # Editing a published question overwrites and returns it to processing.
        save = client.post(
            f"/api/questions/{question_id}/save-regenerate",
            json={
                "command_id": "edit-published",
                "content_revision": body["content_revision"],
                "task_prompt": "已发布题目被再次修改。",
            },
        )
        assert save.status_code == 200
        updated = client.get(f"/api/questions/{question_id}").json()
        assert updated["status"] == "generating"
        assert updated["published_at"] is None
        assert updated["criteria"] is None
        # No historical copy remains: the list still shows exactly one question.
        assert client.get("/api/questions").json()["total"] == 1


def test_admin_can_add_remove_and_edit_criteria() -> None:
    clear_business_data()
    with TestClient(app) as client:
        question_id = _setup_with_generated_question(client)
        detail = client.get(f"/api/questions/{question_id}").json()
        new_criteria = [
            {
                "id": "fact-accuracy",
                "criterion": "核心事实和数据必须准确，不得虚构，引用与来源一致。",
                "pass_score": 8,
            },
            {
                "id": "coverage",
                "criterion": "必须覆盖题目要求的全部要点，遗漏任一要点即不合格。",
                "pass_score": 6,
            },
        ]
        patched = client.patch(
            f"/api/questions/{question_id}/criteria",
            json={
                "command_id": "criteria-1",
                "content_revision": detail["content_revision"],
                "criteria": new_criteria,
            },
        )
        assert patched.status_code == 200, patched.text
        body = patched.json()
        assert [item["id"] for item in body["criteria"]] == ["fact-accuracy", "coverage"]
        assert body["status"] == "pending_review"


def test_invalid_criteria_are_rejected() -> None:
    clear_business_data()
    with TestClient(app) as client:
        question_id = _setup_with_generated_question(client)
        detail = client.get(f"/api/questions/{question_id}").json()

        vague = client.patch(
            f"/api/questions/{question_id}/criteria",
            json={
                "command_id": "criteria-vague",
                "content_revision": detail["content_revision"],
                "criteria": [{"id": "vague", "criterion": "准确性", "pass_score": 5}],
            },
        )
        assert vague.status_code == 422

        out_of_range = client.patch(
            f"/api/questions/{question_id}/criteria",
            json={
                "command_id": "criteria-range",
                "content_revision": detail["content_revision"],
                "criteria": [
                    {
                        "id": "score-range",
                        "criterion": "核心事实准确，不得虚构，引用与来源保持一致。",
                        "pass_score": 11,
                    }
                ],
            },
        )
        assert out_of_range.status_code == 422

        duplicate_ids = client.patch(
            f"/api/questions/{question_id}/criteria",
            json={
                "command_id": "criteria-dup",
                "content_revision": detail["content_revision"],
                "criteria": [
                    {
                        "id": "same-id",
                        "criterion": "核心事实准确，不得虚构，引用与来源保持一致。",
                        "pass_score": 5,
                    },
                    {
                        "id": "same-id",
                        "criterion": "输出覆盖题目全部要点，不得遗漏关键要求。",
                        "pass_score": 5,
                    },
                ],
            },
        )
        assert duplicate_ids.status_code == 422

        private_text = client.patch(
            f"/api/questions/{question_id}/criteria",
            json={
                "command_id": "criteria-private",
                "content_revision": detail["content_revision"],
                "criteria": [
                    {
                        "id": "leaky",
                        "criterion": "结果中不得出现 api_key 等凭证信息。",
                        "pass_score": 5,
                    }
                ],
            },
        )
        assert private_text.status_code == 422


def test_publish_gates_block_generating_and_failed_questions() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client)
        scene = helpers.create_scene(client)
        credential = helpers.issue_credential(client, scene["id"])

        from app.lib.ai_runtime.adapters import FakeRubricGenerator

        failing = helpers.make_case("case-gate")
        failing["task_prompt"] = f"{FakeRubricGenerator.FAIL_MARKER} 无法生成的题目。"
        response = helpers.upload_batch(
            client, credential["token"], helpers.make_batch("cmd-gate", [failing])
        )
        question_id = response.json()["cases"][0]["question_id"]
        detail = client.get(f"/api/questions/{question_id}").json()

        # Generating questions cannot publish.
        publish = client.post(
            f"/api/questions/{question_id}/publication",
            json={"command_id": "publish-early", "content_revision": detail["content_revision"]},
        )
        assert publish.status_code == 409

        helpers.run_worker_until_idle()
        detail = client.get(f"/api/questions/{question_id}").json()
        assert detail["status"] == "generation_failed"

        # Failed questions cannot publish either.
        publish = client.post(
            f"/api/questions/{question_id}/publication",
            json={"command_id": "publish-failed", "content_revision": detail["content_revision"]},
        )
        assert publish.status_code == 409

        # Retry gate: non-failed questions cannot retry.
        retry = client.post(
            f"/api/questions/{question_id}/generation-retry",
            json={"command_id": "retry-misuse", "content_revision": detail["content_revision"]},
        )
        assert retry.status_code == 200
        helpers.run_worker_until_idle()
        detail = client.get(f"/api/questions/{question_id}").json()
        assert detail["status"] == "generation_failed"
        retry_misuse = client.post(
            f"/api/questions/{question_id}/publication",
            json={"command_id": "publish-failed-2", "content_revision": detail["content_revision"]},
        )
        assert retry_misuse.status_code == 409


def test_credential_cannot_read_or_modify_questions() -> None:
    clear_business_data()
    token: str
    with TestClient(app) as client:
        helpers.register_admin(client)
        scene = helpers.create_scene(client)
        credential = helpers.issue_credential(client, scene["id"])
        token = credential["token"]

    # A separate client carrying only the scene credential (no admin session)
    # must not reach any admin library endpoint.
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {token}"}
        listing = client.get("/api/questions", headers=headers)
        assert listing.status_code == 401
        detail = client.get("/api/questions/any-id", headers=headers)
        assert detail.status_code == 401
        publish = client.post(
            "/api/questions/any-id/publication",
            json={"command_id": "x", "content_revision": 1},
            headers=headers,
        )
        assert publish.status_code == 401
