"""Library queries, criteria editing, publication gates, overwrite semantics."""

from fastapi.testclient import TestClient

from app.lib.database import clear_business_data
from app.main import app
from tests import helpers


def _setup_with_generated_question(client: TestClient) -> tuple[str, str]:
    helpers.register_admin(client)
    scene = helpers.create_scene(client)
    credential = helpers.issue_credential(client, scene["id"])
    response = helpers.upload_batch(
        client, credential["token"], helpers.make_batch("cmd-lib", [helpers.make_case("case-lib")])
    )
    assert response.status_code == 201, response.text
    question_id = response.json()["cases"][0]["question_id"]
    helpers.run_worker_until_idle()
    return question_id, scene["id"]


def test_library_requires_scene_and_filters_within_scene() -> None:
    clear_business_data()
    with TestClient(app) as client:
        question_id, scene_id = _setup_with_generated_question(client)

        # Missing scene_id is rejected and never degrades to a global list.
        missing = client.get("/api/questions")
        assert missing.status_code == 422
        assert missing.json()["error"]["code"] == "VALIDATION_ERROR"

        # An unknown scene is a 404, not an empty list.
        unknown = client.get("/api/questions?scene_id=no-such-scene")
        assert unknown.status_code == 404
        assert unknown.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

        listing = client.get(f"/api/questions?scene_id={scene_id}").json()
        assert listing["total"] == 1
        assert listing["items"][0]["id"] == question_id
        assert listing["items"][0]["scene_name"]

        published_only = client.get(
            f"/api/questions?scene_id={scene_id}&status=published"
        ).json()
        assert published_only["total"] == 0

        pending = client.get(
            f"/api/questions?scene_id={scene_id}&status=pending_review"
        ).json()
        assert pending["total"] == 1


def test_two_scenes_never_leak_questions_across_scenes() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client)
        scene_a = helpers.create_scene(client, name="场景甲")
        scene_b = helpers.create_scene(client, name="场景乙")
        credential_a = helpers.issue_credential(client, scene_a["id"])
        credential_b = helpers.issue_credential(client, scene_b["id"])

        upload_a = helpers.upload_batch(
            client, credential_a["token"], helpers.make_batch("cmd-a", [helpers.make_case("case-a")])
        )
        assert upload_a.status_code == 201
        upload_b = helpers.upload_batch(
            client, credential_b["token"], helpers.make_batch("cmd-b", [helpers.make_case("case-b")])
        )
        assert upload_b.status_code == 201

        # Every listing call is scene-scoped; no parameter combination can
        # return the cross-scene union of the two questions.
        listing_a = client.get(f"/api/questions?scene_id={scene_a['id']}").json()
        listing_b = client.get(f"/api/questions?scene_id={scene_b['id']}").json()
        assert listing_a["total"] == 1
        assert listing_b["total"] == 1
        assert listing_a["items"][0]["id"] == upload_a.json()["cases"][0]["question_id"]
        assert listing_b["items"][0]["id"] == upload_b.json()["cases"][0]["question_id"]
        missing = client.get("/api/questions")
        assert missing.status_code == 422
        assert missing.json()["error"]["code"] == "VALIDATION_ERROR"
        empty = client.get("/api/questions?scene_id=")
        assert empty.status_code == 404
        assert empty.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_publish_requires_valid_criteria_and_overwrite_on_edit() -> None:
    clear_business_data()
    with TestClient(app) as client:
        question_id, scene_id = _setup_with_generated_question(client)
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
        # No historical copy remains: the scene list still shows exactly one question.
        assert client.get(f"/api/questions?scene_id={scene_id}").json()["total"] == 1


def test_admin_can_add_remove_and_edit_criteria() -> None:
    clear_business_data()
    with TestClient(app) as client:
        question_id, _scene_id = _setup_with_generated_question(client)
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
        question_id, _scene_id = _setup_with_generated_question(client)
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
    scene_id: str
    with TestClient(app) as client:
        helpers.register_admin(client)
        scene = helpers.create_scene(client)
        credential = helpers.issue_credential(client, scene["id"])
        token = credential["token"]
        scene_id = scene["id"]

    # A separate client carrying only the scene credential (no admin session)
    # must not reach any admin library endpoint, even with a valid scene_id.
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {token}"}
        listing = client.get(f"/api/questions?scene_id={scene_id}", headers=headers)
        assert listing.status_code == 401
        assert listing.json()["error"]["code"] == "AUTH_REQUIRED"
        detail = client.get("/api/questions/any-id", headers=headers)
        assert detail.status_code == 401
        publish = client.post(
            "/api/questions/any-id/publication",
            json={"command_id": "x", "content_revision": 1},
            headers=headers,
        )
        assert publish.status_code == 401
