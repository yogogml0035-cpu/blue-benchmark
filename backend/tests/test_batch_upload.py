"""External batch intake: idempotency, atomicity, privacy, isolation."""

import copy

from fastapi.testclient import TestClient

from app.lib.database import clear_business_data
from app.main import app
from tests import helpers


def _setup(client: TestClient) -> tuple[str, str]:
    helpers.register_admin(client)
    scene = helpers.create_scene(client)
    credential = helpers.create_credential(client, scene["id"])
    return scene["id"], credential["token"]


def test_batch_upload_requires_credential() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client)
        response = client.post(
            "/api/external/question-batches",
            json=helpers.make_batch("cmd-1", [helpers.make_case()]),
        )
        assert response.status_code == 401
        response = client.post(
            "/api/external/question-batches",
            json=helpers.make_batch("cmd-1", [helpers.make_case()]),
            headers={"Authorization": "Bearer sep_obviously-invalid"},
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "CREDENTIAL_INVALID"


def test_revoked_credential_cannot_upload() -> None:
    clear_business_data()
    with TestClient(app) as client:
        scene_id, token = _setup(client)
        status = client.get(f"/api/scenes/{scene_id}").json()
        credential_id = status["credential"]["credential_id"]
        assert client.delete(f"/api/scenes/{scene_id}/credentials/{credential_id}").status_code == 200
        response = helpers.upload_batch(
            client, token, helpers.make_batch("cmd-revoked", [helpers.make_case()])
        )
        assert response.status_code == 401


def test_batch_upload_saves_six_materials_per_question() -> None:
    clear_business_data()
    with TestClient(app) as client:
        scene_id, token = _setup(client)
        cases = [helpers.make_case("case-a"), helpers.make_case("case-b", title="另一道题")]
        response = helpers.upload_batch(client, token, helpers.make_batch("cmd-six", cases))
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["scene_id"] == scene_id
        assert body["accepted_case_count"] == 2
        assert [item["status"] for item in body["cases"]] == ["generating", "generating"]

        question_id = body["cases"][0]["question_id"]
        detail = client.get(f"/api/questions/{question_id}").json()
        assert detail["task_prompt"].startswith("请把提供的新闻素材")
        assert detail["reference_examples"][0]["content_text"].startswith("老师提供")
        assert detail["bad_cases"][0]["teacher_feedback_texts"][0].startswith("语气太随意")
        assert detail["memory_materials"][0]["source_label"] == "业务记忆"
        assert detail["reference_answer"] == "这是一份老师认可的标准答案。"
        assert detail["criteria"] is None
        assert detail["status"] == "generating"
        assert detail["next_action"] == "wait_for_generation"


def test_idempotent_replay_and_payload_conflict() -> None:
    clear_business_data()
    with TestClient(app) as client:
        scene_id, token = _setup(client)
        payload = helpers.make_batch("cmd-idem", [helpers.make_case("case-x")])
        first = helpers.upload_batch(client, token, payload)
        assert first.status_code == 201
        replay = helpers.upload_batch(client, token, copy.deepcopy(payload))
        assert replay.status_code == 201
        assert replay.json() == first.json()

        # Only one question exists after the replay.
        listing = client.get(f"/api/questions?scene_id={scene_id}").json()
        assert listing["total"] == 1

        # Same command with a changed payload must conflict.
        changed = copy.deepcopy(payload)
        changed["cases"][0]["title"] = "改动后的标题"
        conflict = helpers.upload_batch(client, token, changed)
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "COMMAND_ID_REUSED"


def test_failed_batch_leaves_no_trace_and_new_command_succeeds() -> None:
    clear_business_data()
    with TestClient(app) as client:
        scene_id, token = _setup(client)
        bad_case = helpers.make_case("case-bad")
        bad_case["reference_answer"] = "   "  # blank answer after strip -> invalid
        good_case = helpers.make_case("case-good")
        response = helpers.upload_batch(
            client, token, helpers.make_batch("cmd-fail", [good_case, bad_case])
        )
        # Blank answer fails pydantic validation -> whole request rejected.
        assert response.status_code == 422

        # A valid batch under a new command succeeds; nothing half-created.
        response = helpers.upload_batch(
            client, token, helpers.make_batch("cmd-ok", [good_case])
        )
        assert response.status_code == 201, response.text
        assert client.get(f"/api/questions?scene_id={scene_id}").json()["total"] == 1


def test_private_content_is_rejected_for_entire_batch() -> None:
    clear_business_data()
    with TestClient(app) as client:
        scene_id, token = _setup(client)
        leaking = helpers.make_case("case-leak")
        leaking["memory_materials"] = [
            {
                "client_ref_id": "mem-leak",
                "source_label": "项目记忆",
                "content_text": "配置在 /Users/hsikey/.env 中保存。",
            }
        ]
        clean = helpers.make_case("case-clean")
        response = helpers.upload_batch(
            client, token, helpers.make_batch("cmd-leak", [clean, leaking])
        )
        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "BATCH_CASE_INVALID"
        problems = {item["client_case_id"] for item in error["details"]["cases"]}
        assert problems == {"case-leak"}
        # Atomicity: the clean case in the same batch is not created either.
        assert client.get(f"/api/questions?scene_id={scene_id}").json()["total"] == 0


def test_duplicate_client_case_id_conflicts_without_half_batch() -> None:
    clear_business_data()
    with TestClient(app) as client:
        scene_id, token = _setup(client)
        first = helpers.upload_batch(
            client, token, helpers.make_batch("cmd-dup-1", [helpers.make_case("case-dup")])
        )
        assert first.status_code == 201
        second = helpers.upload_batch(
            client,
            token,
            helpers.make_batch(
                "cmd-dup-2",
                [helpers.make_case("case-dup"), helpers.make_case("case-other")],
            ),
        )
        assert second.status_code == 422
        assert client.get(f"/api/questions?scene_id={scene_id}").json()["total"] == 1


def test_materials_are_isolated_between_questions() -> None:
    clear_business_data()
    with TestClient(app) as client:
        scene_id, token = _setup(client)
        shared_memory = {
            "client_ref_id": "mem-shared",
            "source_label": "共享记忆",
            "content_text": "两道题都会用到的记忆原文。",
        }
        case_a = helpers.make_case("case-shared-a", memory_materials=[dict(shared_memory)])
        case_b = helpers.make_case("case-shared-b", memory_materials=[dict(shared_memory)])
        response = helpers.upload_batch(
            client, token, helpers.make_batch("cmd-shared", [case_a, case_b])
        )
        assert response.status_code == 201, response.text
        ids = [item["question_id"] for item in response.json()["cases"]]

        helpers.run_worker_until_idle()

        # Editing question A's materials must not touch question B.
        detail_a = client.get(f"/api/questions/{ids[0]}").json()
        save = client.post(
            f"/api/questions/{ids[0]}/save-regenerate",
            json={
                "command_id": "edit-a",
                "content_revision": detail_a["content_revision"],
                "memory_materials": [
                    {
                        "client_ref_id": "mem-new",
                        "source_label": "新记忆",
                        "content_text": "只有题目 A 持有的新记忆。",
                    }
                ],
            },
        )
        assert save.status_code == 200, save.text
        detail_b = client.get(f"/api/questions/{ids[1]}").json()
        assert detail_b["memory_materials"][0]["content_text"] == "两道题都会用到的记忆原文。"

        # Let question A's regeneration finish; generating questions are
        # protected from deletion.
        helpers.run_worker_until_idle()

        # Deleting question A leaves B intact.
        detail_a = client.get(f"/api/questions/{ids[0]}").json()
        deleted = client.request(
            "DELETE",
            f"/api/questions/{ids[0]}",
            json={"content_revision": detail_a["content_revision"]},
        )
        assert deleted.status_code == 204
        assert client.get(f"/api/questions/{ids[1]}").status_code == 200
        assert client.get(f"/api/questions?scene_id={scene_id}").json()["total"] == 1


def test_scene_credentials_are_isolated_between_scenes() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client)
        scene_a = helpers.create_scene(client, name="场景甲")
        scene_b = helpers.create_scene(client, name="场景乙")
        credential_b = helpers.create_credential(client, scene_b["id"])

        response = helpers.upload_batch(
            client, credential_b["token"], helpers.make_batch("cmd-iso", [helpers.make_case()])
        )
        assert response.status_code == 201
        assert response.json()["scene_id"] == scene_b["id"]

        # Question lives only in scene B.
        listing_a = client.get(f"/api/questions?scene_id={scene_a['id']}").json()
        listing_b = client.get(f"/api/questions?scene_id={scene_b['id']}").json()
        assert listing_a["total"] == 0
        assert listing_b["total"] == 1
