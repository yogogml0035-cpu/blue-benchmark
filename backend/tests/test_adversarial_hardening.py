"""Regression tests for the adversarial-hardening fixes.

Each test pins one concrete exploit the review round identified: privacy
backstop bypasses, unscanned fields, vague-label wrapping, single-admin
atomicity, state-machine guards, and compare-and-sap staleness.
"""

from fastapi.testclient import TestClient

from app.features.question_library import rubric_rules
from app.lib.database import clear_business_data
from app.main import app
from tests import helpers


def test_privacy_backstop_unicode_and_coverage_bypasses() -> None:
    # Zero-width splitting of a credential keyword.
    assert rubric_rules.contains_private_content("pass\u200bword=abc123") == "凭证"
    # Fullwidth homoglyphs fold under NFKC.
    assert rubric_rules.contains_private_content("ｐａｓｓｗｏｒｄ=abc123") == "凭证"
    # Word-joiner splitting of api_key.
    assert rubric_rules.contains_private_content("api\u2060_key=xyz") == "凭证"
    # Non-C drive letters and UNC shares.
    assert rubric_rules.contains_private_content("备份在 D:\\secrets\\key.pem") == "主机路径"
    assert rubric_rules.contains_private_content("见 \\\\fileserver\\share\\secret.xlsx") == "主机路径"
    # High-signal secret value shapes.
    assert rubric_rules.contains_private_content("key is sk-proj-abcdefghijklmnop1234") == "凭证"
    assert rubric_rules.contains_private_content("token sep_abcdefghijklmnopqrstuv") == "凭证"
    assert rubric_rules.contains_private_content("AccessKeyId AKIA1234567890AB") == "凭证"
    # Clean business text passes.
    assert rubric_rules.contains_private_content("把会议结论整理成纪要") is None


def test_title_and_client_case_id_are_scanned_on_upload() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client)
        scene = helpers.create_scene(client)
        credential = helpers.create_credential(client, scene["id"])
        leaking = helpers.make_case("case-title-leak")
        leaking["title"] = "密码是 hunter2，备份在 /Users/hsikey/.ssh/id_rsa"
        response = helpers.upload_batch(
            client, credential["token"], helpers.make_batch("cmd-title-leak", [leaking])
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "BATCH_CASE_INVALID"


def test_admin_title_edit_is_scanned() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client)
        scene = helpers.create_scene(client)
        credential = helpers.create_credential(client, scene["id"])
        response = helpers.upload_batch(
            client, credential["token"], helpers.make_batch("cmd-title-edit", [helpers.make_case("case-t")])
        )
        question_id = response.json()["cases"][0]["question_id"]
        detail = client.get(f"/api/questions/{question_id}").json()
        rename = client.patch(
            f"/api/questions/{question_id}/title",
            json={
                "command_id": "rename-leak",
                "content_revision": detail["content_revision"],
                "title": "密钥在 C:\\secrets\\token.txt",
            },
        )
        assert rename.status_code == 422
        assert rename.json()["error"]["code"] == "PRIVATE_CONTENT_REJECTED"


def test_vague_labels_wrapped_in_punctuation_are_rejected() -> None:
    for wrapped in ["准确性，", "、准确性", "准确性：", "【准确性】", "「准确性」", '"准确性"', "准确性、创新性、完整性"]:
        assert rubric_rules.is_vague_criterion(wrapped), wrapped
    # A genuinely actionable criterion is not rejected.
    assert not rubric_rules.is_vague_criterion("核心事实和数据准确，不得虚构，引用与来源一致。")


def test_ai_and_admin_paths_share_the_actionability_floor() -> None:
    assert rubric_rules.MIN_CRITERION_LENGTH == 8
    # Short labels fail the shared validator used by the worker.
    for short in ["好", "准确", "1234567"]:
        try:
            rubric_rules.validate_criterion_text(short)
            raised = False
        except ValueError:
            raised = True
        assert raised, short


def test_single_admin_registration_is_atomic() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client, username="the-admin")
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/register",
            json={"username": "impostor", "password": "impostor-password"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ADMIN_EXISTS"
    # Login as the impostor must fail: it was never created.
    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"identifier": "impostor", "password": "impostor-password"},
        )
        assert login.status_code == 401


def test_logout_requires_an_authenticated_session() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client)
    with TestClient(app) as client:  # anonymous
        response = client.post("/api/auth/logout")
        assert response.status_code == 401


def test_login_identifier_does_not_use_like_wildcards() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client, username="the-admin")
    with TestClient(app) as client:
        # '%' would match any row under LIKE; it must not resolve an account.
        response = client.post(
            "/api/auth/login", json={"identifier": "%", "password": "whatever-1"}
        )
        assert response.status_code == 401


def test_no_change_save_and_regenerate_is_rejected() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client)
        scene = helpers.create_scene(client)
        credential = helpers.create_credential(client, scene["id"])
        response = helpers.upload_batch(
            client, credential["token"], helpers.make_batch("cmd-nochange", [helpers.make_case("case-n")])
        )
        question_id = response.json()["cases"][0]["question_id"]
        helpers.run_worker_until_idle()
        detail = client.get(f"/api/questions/{question_id}").json()
        # Same materials, no title change -> rejected instead of burning a call.
        save = client.post(
            f"/api/questions/{question_id}/save-regenerate",
            json={"command_id": "noop", "content_revision": detail["content_revision"]},
        )
        assert save.status_code == 409
        assert save.json()["error"]["code"] == "NO_MATERIAL_CHANGE"


def test_published_question_rejects_criteria_patch() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client)
        scene = helpers.create_scene(client)
        credential = helpers.create_credential(client, scene["id"])
        response = helpers.upload_batch(
            client, credential["token"], helpers.make_batch("cmd-pubpatch", [helpers.make_case("case-p")])
        )
        question_id = response.json()["cases"][0]["question_id"]
        helpers.run_worker_until_idle()
        detail = client.get(f"/api/questions/{question_id}").json()
        confirmed = client.patch(
            f"/api/questions/{question_id}/criteria",
            json={
                "command_id": "criteria-before-publish",
                "content_revision": detail["content_revision"],
                "criteria": [
                    {
                        "id": "confirmed-rule",
                        "criterion": "输出必须覆盖题目要求的全部要点，不得遗漏关键信息。",
                        "pass_score": 6,
                    }
                ],
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        publish = client.post(
            f"/api/questions/{question_id}/publication",
            json={"command_id": "pub", "content_revision": confirmed.json()["content_revision"]},
        )
        assert publish.status_code == 200
        patched = client.get(f"/api/questions/{question_id}").json()
        edit = client.patch(
            f"/api/questions/{question_id}/criteria",
            json={
                "command_id": "criteria-after-publish",
                "content_revision": patched["content_revision"],
                "criteria": [
                    {
                        "id": "sneaky",
                        "criterion": "悄悄替换已发布题目的评分合同，这是不允许的操作。",
                        "pass_score": 5,
                    }
                ],
            },
        )
        assert edit.status_code == 409
        assert edit.json()["error"]["code"] == "PUBLISHED_REOPEN_REQUIRED"


def test_whitespace_only_material_returns_422_not_500() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client)
        scene = helpers.create_scene(client)
        credential = helpers.create_credential(client, scene["id"])
        response = helpers.upload_batch(
            client, credential["token"], helpers.make_batch("cmd-blank", [helpers.make_case("case-b")])
        )
        question_id = response.json()["cases"][0]["question_id"]
        helpers.run_worker_until_idle()
        detail = client.get(f"/api/questions/{question_id}").json()
        save = client.post(
            f"/api/questions/{question_id}/save-regenerate",
            json={
                "command_id": "blank-answer",
                "content_revision": detail["content_revision"],
                "reference_answer": "   ",
            },
        )
        assert save.status_code == 422, save.text


def test_delete_is_blocked_while_generating() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client)
        scene = helpers.create_scene(client)
        credential = helpers.create_credential(client, scene["id"])
        response = helpers.upload_batch(
            client, credential["token"], helpers.make_batch("cmd-delgen", [helpers.make_case("case-d")])
        )
        question_id = response.json()["cases"][0]["question_id"]
        # Status is generating; deletion must be refused until it settles.
        delete = client.request(
            "DELETE", f"/api/questions/{question_id}",
            json={"command_id": "del-adv-1", "content_revision": 1},
        )
        assert delete.status_code == 409
        assert delete.json()["error"]["code"] == "RUBRIC_GENERATING"
        helpers.run_worker_until_idle()
        detail = client.get(f"/api/questions/{question_id}").json()
        deleted = client.request(
            "DELETE",
            f"/api/questions/{question_id}",
            json={"command_id": "del-adv-2", "content_revision": detail["content_revision"]},
        )
        assert deleted.status_code == 202
        helpers.run_worker_until_idle()
        assert client.get(f"/api/questions/{question_id}").status_code == 404


def test_pass_semantics_clamp_to_the_fixed_ten_point_scale() -> None:
    criteria = [{"id": "a", "criterion": "事实准确。", "pass_score": 7}]
    # A score above the fixed 10-point scale is invalid, not a pass.
    assert rubric_rules.evaluate_question_pass(criteria, {"a": 999}) is False
    assert rubric_rules.evaluate_question_pass(criteria, {"a": 7}) is True
    # An out-of-range stored pass_score also fails closed.
    assert rubric_rules.evaluate_question_pass(
        [{"id": "a", "criterion": "x", "pass_score": 42}], {"a": 10}
    ) is False


def test_conditional_update_is_single_writer() -> None:
    """The compare-and-swap must admit exactly one writer per revision.

    SQLite does not support SELECT ... FOR UPDATE, so the fix relies on a
    conditional UPDATE keyed on ``content_revision``. Two updates racing on
    the same expected revision: the first wins, the second sees no row.
    """

    from datetime import datetime, timezone

    from app.features.question_library import repository
    from app.lib.database import session_scope

    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client)
        scene = helpers.create_scene(client)
        credential = helpers.create_credential(client, scene["id"])
        response = helpers.upload_batch(
            client, credential["token"], helpers.make_batch("cmd-cas", [helpers.make_case("case-cas")])
        )
        question_id = response.json()["cases"][0]["question_id"]

    now = datetime.now(timezone.utc)
    with session_scope() as session:
        first = repository.update_fields(
            session, question_id, expected_revision=1, now=now,
            title="写入者一", content_revision=2,
        )
    assert first is not None
    assert first.title == "写入者一"
    assert first.content_revision == 2

    # The second writer still believes the revision is 1 and must lose.
    with session_scope() as session:
        second = repository.update_fields(
            session, question_id, expected_revision=1, now=now,
            title="写入者二", content_revision=2,
        )
    assert second is None

    # The stored title must be the first writer's, revision advanced once.
    with session_scope() as session:
        record = repository.get_question(session, question_id)
    assert record is not None
    assert record.title == "写入者一"
    assert record.content_revision == 2
