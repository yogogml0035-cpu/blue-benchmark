"""Teacher confirmation, review reopen, and protected hard-delete contracts."""

from fastapi.testclient import TestClient

from app.lib.database import clear_business_data
from app.main import app
from tests import helpers


def _setup_pending_review(client: TestClient) -> str:
    helpers.register_admin(client)
    scene = helpers.create_scene(client)
    credential = helpers.create_credential(client, scene["id"])
    response = helpers.upload_batch(
        client, credential["token"], helpers.make_batch("cmd-review", [helpers.make_case("case-review")])
    )
    assert response.status_code == 201, response.text
    question_id = response.json()["cases"][0]["question_id"]
    helpers.run_worker_until_idle()
    return question_id


def _confirm_criteria(client: TestClient, question_id: str) -> dict:
    detail = client.get(f"/api/questions/{question_id}").json()
    patched = client.patch(
        f"/api/questions/{question_id}/criteria",
        json={
            "command_id": "criteria-save",
            "content_revision": detail["content_revision"],
            "criteria": [
                {
                    "id": "teacher-rule",
                    "criterion": "输出必须覆盖题目要求的全部要点，不得遗漏关键信息。",
                    "pass_score": 7,
                }
            ],
        },
    )
    assert patched.status_code == 200, patched.text
    return patched.json()


def _publish(client: TestClient, question_id: str) -> dict:
    detail = client.get(f"/api/questions/{question_id}").json()
    published = client.post(
        f"/api/questions/{question_id}/publication",
        json={"command_id": "publish-cmd", "content_revision": detail["content_revision"]},
    )
    assert published.status_code == 200, published.text
    return published.json()


def test_save_and_publish_are_separate_steps() -> None:
    clear_business_data()
    with TestClient(app) as client:
        question_id = _setup_pending_review(client)
        detail = client.get(f"/api/questions/{question_id}").json()
        assert detail["status"] == "pending_review"
        assert detail["criteria_confirmed"] is False
        assert detail["next_action"] == "review_criteria"
        assert detail["delete_confirmation_required"] is False

        confirmed = _confirm_criteria(client, question_id)
        assert confirmed["criteria_confirmed"] is True
        assert confirmed["next_action"] == "publish"
        assert confirmed["status"] == "pending_review"

        published = _publish(client, question_id)
        assert published["status"] == "published"
        assert published["next_action"] == "published"
        assert published["delete_confirmation_required"] is True


def test_review_reopen_preserves_materials_and_criteria() -> None:
    clear_business_data()
    with TestClient(app) as client:
        question_id = _setup_pending_review(client)
        _confirm_criteria(client, question_id)
        published = _publish(client, question_id)

        reopened = client.post(
            f"/api/questions/{question_id}/review-reopen",
            json={
                "command_id": "reopen-1",
                "content_revision": published["content_revision"],
            },
        )
        assert reopened.status_code == 200, reopened.text
        body = reopened.json()
        assert body["status"] == "pending_review"
        assert body["next_action"] == "publish"
        assert body["published_at"] is None
        # Materials, criteria and the confirmation fact are preserved.
        assert body["criteria_confirmed"] is True
        assert [item["id"] for item in body["criteria"]] == ["teacher-rule"]
        assert body["task_prompt"] == published["task_prompt"]
        # Publish history stays true to protect deletion.
        assert body["delete_confirmation_required"] is True

        # Repeating reopen on a non-published question conflicts.
        again = client.post(
            f"/api/questions/{question_id}/review-reopen",
            json={"command_id": "reopen-2", "content_revision": body["content_revision"]},
        )
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "REVIEW_REOPEN_NOT_AVAILABLE"


def test_review_reopen_requires_published_state_and_fresh_revision() -> None:
    clear_business_data()
    with TestClient(app) as client:
        question_id = _setup_pending_review(client)
        detail = client.get(f"/api/questions/{question_id}").json()

        # Never published: reopen is unavailable.
        blocked = client.post(
            f"/api/questions/{question_id}/review-reopen",
            json={"command_id": "reopen-early", "content_revision": detail["content_revision"]},
        )
        assert blocked.status_code == 409
        assert blocked.json()["error"]["code"] == "REVIEW_REOPEN_NOT_AVAILABLE"

        _confirm_criteria(client, question_id)
        published = _publish(client, question_id)
        # Stale revision: rejected.
        stale = client.post(
            f"/api/questions/{question_id}/review-reopen",
            json={"command_id": "reopen-stale", "content_revision": 999},
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "STALE_REVISION"
        assert published["status"] == "published"


def test_republish_after_reopen_keeps_single_record() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client)
        scene = helpers.create_scene(client)
        credential = helpers.create_credential(client, scene["id"])
        response = helpers.upload_batch(
            client, credential["token"], helpers.make_batch("cmd-cycle", [helpers.make_case("case-cycle")])
        )
        question_id = response.json()["cases"][0]["question_id"]
        helpers.run_worker_until_idle()

        _confirm_criteria(client, question_id)
        _publish(client, question_id)
        detail = client.get(f"/api/questions/{question_id}").json()
        client.post(
            f"/api/questions/{question_id}/review-reopen",
            json={"command_id": "reopen", "content_revision": detail["content_revision"]},
        )

        # Adjust the saved criteria and publish again — no version history.
        current = client.get(f"/api/questions/{question_id}").json()
        patched = client.patch(
            f"/api/questions/{question_id}/criteria",
            json={
                "command_id": "criteria-adjust",
                "content_revision": current["content_revision"],
                "criteria": [
                    {
                        "id": "adjusted-rule",
                        "criterion": "重新打开后调整的评分标准，仍然必须可执行且完整。",
                        "pass_score": 8,
                    }
                ],
            },
        )
        assert patched.status_code == 200, patched.text
        republished = client.post(
            f"/api/questions/{question_id}/publication",
            json={
                "command_id": "publish-again",
                "content_revision": patched.json()["content_revision"],
            },
        )
        assert republished.status_code == 200
        assert republished.json()["status"] == "published"
        listing = client.get(f"/api/questions?scene_id={scene['id']}").json()
        assert listing["total"] == 1


def test_delete_gate_for_ever_published_questions() -> None:
    clear_business_data()
    with TestClient(app) as client:
        question_id = _setup_pending_review(client)
        _confirm_criteria(client, question_id)
        published = _publish(client, question_id)
        title = published["title"]

        # Still published: reopen first.
        blocked = client.request(
            "DELETE",
            f"/api/questions/{question_id}",
            json={"command_id": "del-blocked", "content_revision": published["content_revision"]},
        )
        assert blocked.status_code == 409
        assert blocked.json()["error"]["code"] == "PUBLISHED_REOPEN_REQUIRED"

        reopened = client.post(
            f"/api/questions/{question_id}/review-reopen",
            json={"command_id": "reopen-del", "content_revision": published["content_revision"]},
        )
        revision = reopened.json()["content_revision"]

        # No confirmation title: rejected, even after a fresh reload.
        missing = client.request(
            "DELETE", f"/api/questions/{question_id}",
            json={"command_id": "del-missing", "content_revision": revision},
        )
        assert missing.status_code == 422
        assert missing.json()["error"]["code"] == "DELETE_CONFIRMATION_MISMATCH"

        # Wrong title: rejected.
        wrong = client.request(
            "DELETE",
            f"/api/questions/{question_id}",
            json={"command_id": "del-wrong", "content_revision": revision,
                  "confirmation_title": title + "x"},
        )
        assert wrong.status_code == 422
        assert wrong.json()["error"]["code"] == "DELETE_CONFIRMATION_MISMATCH"

        # Exact current title: accepted (202), then the cleanup worker
        # completes the cross-store deletion before the question 404s.
        deleted = client.request(
            "DELETE",
            f"/api/questions/{question_id}",
            json={"command_id": "del-exact", "content_revision": revision,
                  "confirmation_title": title},
        )
        assert deleted.status_code == 202, deleted.text
        assert deleted.json()["status"] == "deleting"
        helpers.run_worker_until_idle()
        assert client.get(f"/api/questions/{question_id}").status_code == 404


def test_delete_confirmation_title_is_normalized() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client)
        scene = helpers.create_scene(client)
        credential = helpers.create_credential(client, scene["id"])
        case = helpers.make_case("case-nfc")
        # NFD-decomposed title; the delete confirmation arrives recomposed + padded.
        case["title"] = "标题\u0065\u0301的分解形式"
        response = helpers.upload_batch(
            client, credential["token"], helpers.make_batch("cmd-nfc", [case])
        )
        question_id = response.json()["cases"][0]["question_id"]
        helpers.run_worker_until_idle()
        _confirm_criteria(client, question_id)
        _publish(client, question_id)
        detail = client.get(f"/api/questions/{question_id}").json()
        client.post(
            f"/api/questions/{question_id}/review-reopen",
            json={"command_id": "reopen-nfc", "content_revision": detail["content_revision"]},
        )
        reopened = client.get(f"/api/questions/{question_id}").json()

        padded_nfc = "  " + "\u00e9".join(reopened["title"].split("\u0065\u0301")) + "  "
        deleted = client.request(
            "DELETE",
            f"/api/questions/{question_id}",
            json={"command_id": "del-nfc", "content_revision": reopened["content_revision"],
                  "confirmation_title": padded_nfc},
        )
        assert deleted.status_code == 202, deleted.text
        helpers.run_worker_until_idle()
        assert client.get(f"/api/questions/{question_id}").status_code == 404


def test_never_published_questions_delete_with_plain_confirmation() -> None:
    clear_business_data()
    with TestClient(app) as client:
        question_id = _setup_pending_review(client)
        detail = client.get(f"/api/questions/{question_id}").json()
        assert detail["delete_confirmation_required"] is False

        deleted = client.request(
            "DELETE",
            f"/api/questions/{question_id}",
            json={"command_id": "del-plain", "content_revision": detail["content_revision"]},
        )
        assert deleted.status_code == 202
        helpers.run_worker_until_idle()
        assert client.get(f"/api/questions/{question_id}").status_code == 404


def test_delete_cleans_up_generation_jobs() -> None:
    clear_business_data()
    with TestClient(app) as client:
        question_id = _setup_pending_review(client)
        detail = client.get(f"/api/questions/{question_id}").json()
        deleted = client.request(
            "DELETE",
            f"/api/questions/{question_id}",
            json={"command_id": "del-jobs", "content_revision": detail["content_revision"]},
        )
        assert deleted.status_code == 202
        cleanup_operation_id = deleted.json()["operation_id"]

    helpers.run_worker_until_idle()
    assert client.get(f"/api/questions/{question_id}").status_code == 404

    from sqlalchemy import select

    from app.lib.database import session_scope
    from app.lib.database.models import AgentRunAttemptRow, OperationJobRow

    with session_scope() as session:
        generation_jobs = session.execute(
            select(OperationJobRow).where(
                OperationJobRow.target_type == "eval_question",
                OperationJobRow.target_id == question_id,
            )
        ).scalars().all()
        generation_attempts = session.execute(
            select(AgentRunAttemptRow).where(
                AgentRunAttemptRow.target_type == "eval_question",
                AgentRunAttemptRow.target_id == question_id,
            )
        ).scalars().all()
        receipts = session.execute(
            select(OperationJobRow).where(OperationJobRow.id == cleanup_operation_id)
        ).scalars().all()
    assert generation_jobs == []
    assert generation_attempts == []
    # The minimal content-free cleanup receipt survives for idempotency/audit.
    assert len(receipts) == 1 and receipts[0].status == "succeeded"
    assert receipts[0].result_json is not None
    assert "criteria" not in str(receipts[0].result_json)


def test_delete_stale_revision_is_rejected() -> None:
    clear_business_data()
    with TestClient(app) as client:
        question_id = _setup_pending_review(client)
        stale = client.request(
            "DELETE", f"/api/questions/{question_id}",
            json={"command_id": "del-stale", "content_revision": 42},
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "STALE_REVISION"
        assert client.get(f"/api/questions/{question_id}").status_code == 200


def test_cas_backstops_reject_raced_state_transitions() -> None:
    """Repository-level predicates are the atomic backstop for state gates.

    Even when a snapshot check passes, the conditional UPDATE/DELETE must
    refuse to apply a transition whose source state no longer holds. This is
    what keeps concurrent publish/delete/criteria commands last-writer-LOSES.
    """

    from datetime import datetime, timezone

    from app.features.question_library import repository
    from app.lib.database import session_scope
    from app.lib.database.models import EvalQuestionRow

    clear_business_data()
    with TestClient(app) as client:
        question_id = _setup_pending_review(client)
        _confirm_criteria(client, question_id)
        _publish(client, question_id)

    now = datetime.now(timezone.utc)

    # Reopen CAS requires the published source state; a row already reopened
    # (pending_review) refuses a second transition.
    with session_scope() as session:
        record = repository.get_question(session, question_id)
        assert record is not None and record.status == "published"
        revision = record.content_revision
    with session_scope() as session:
        raced = repository.update_fields(
            session,
            question_id,
            expected_revision=revision,
            now=now,
            expected_status="pending_review",  # wrong source state on purpose
            status="generating",
        )
    assert raced is None
    with session_scope() as session:
        still = repository.get_question(session, question_id)
    assert still is not None and still.status == "published"

    # A published row refuses deletion at the API gate even with the right
    # revision (the old synchronous hard-delete repository path is gone; the
    # accepted-deletion flow is the only delete route).
    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"identifier": "admin", "password": "platform-admin-password"},
        )
        assert login.status_code == 200, login.text
        refused = client.request(
            "DELETE",
            f"/api/questions/{question_id}",
            json={"command_id": "del-cas-pub", "content_revision": revision},
        )
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "PUBLISHED_REOPEN_REQUIRED"
        assert repository is not None  # repository import still used above
    with session_scope() as session:
        assert repository.question_exists(session, question_id)

    # After a real reopen the guarded delete succeeds with the same revision.
    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"identifier": "admin", "password": "platform-admin-password"},
        )
        assert login.status_code == 200, login.text
        detail = client.get(f"/api/questions/{question_id}").json()
        reopened = client.post(
            f"/api/questions/{question_id}/review-reopen",
            json={"command_id": "reopen-cas", "content_revision": detail["content_revision"]},
        )
        assert reopened.status_code == 200, reopened.text
        title = reopened.json()["title"]
        deleted = client.request(
            "DELETE",
            f"/api/questions/{question_id}",
            json={
                "command_id": "del-cas",
                "content_revision": reopened.json()["content_revision"],
                "confirmation_title": title,
            },
        )
        assert deleted.status_code == 202
        helpers.run_worker_until_idle()
        assert client.get(f"/api/questions/{question_id}").status_code == 404


def test_publish_cas_requires_confirmation_facts() -> None:
    """The publish CAS folds criteria_confirmed into the atomic predicate."""

    from datetime import datetime, timezone

    from app.features.question_library import repository
    from app.lib.database import session_scope
    from app.lib.database.models import EvalQuestionRow

    clear_business_data()
    with TestClient(app) as client:
        question_id = _setup_pending_review(client)
        detail = client.get(f"/api/questions/{question_id}").json()
        revision = detail["content_revision"]

    now = datetime.now(timezone.utc)
    # Attempting to publish an unconfirmed draft via the CAS backstop fails:
    # the predicate requires criteria_confirmed=true in the same statement.
    with session_scope() as session:
        raced = repository.update_fields(
            session,
            question_id,
            expected_revision=revision,
            now=now,
            expected_status="pending_review",
            extra_conditions=[
                EvalQuestionRow.criteria_confirmed.is_(True),
                EvalQuestionRow.criteria_json.is_not(None),
            ],
            status="published",
        )
    assert raced is None
    with session_scope() as session:
        record = repository.get_question(session, question_id)
    assert record is not None and record.status == "pending_review"


def test_publish_cas_rejects_missing_criteria_json() -> None:
    """The criteria_json IS NOT NULL half of the publish predicate."""

    from datetime import datetime, timezone

    from sqlalchemy import null

    from app.features.question_library import repository
    from app.lib.database import session_scope
    from app.lib.database.models import EvalQuestionRow

    clear_business_data()
    with TestClient(app) as client:
        question_id = _setup_pending_review(client)

    now = datetime.now(timezone.utc)
    # Simulate a row whose criteria were wiped to SQL NULL while the
    # confirmed flag happens to be set: publish must still be refused.
    # (``null()`` is required — a plain None binds as JSON null, not SQL NULL.)
    with session_scope() as session:
        record = repository.update_fields(
            session,
            question_id,
            expected_revision=1,
            now=now,
            criteria_json=null(),
            criteria_confirmed=True,
        )
    assert record is not None
    with session_scope() as session:
        raced = repository.update_fields(
            session,
            question_id,
            expected_revision=record.content_revision,
            now=now,
            expected_status="pending_review",
            extra_conditions=[
                EvalQuestionRow.criteria_confirmed.is_(True),
                EvalQuestionRow.criteria_json.is_not(None),
            ],
            status="published",
        )
    assert raced is None


def test_retry_cas_requires_generation_failed_source() -> None:
    """A teacher criteria save that wins the race blocks a trailing retry.

    Mirrors the first-round finding: both commands pass the snapshot checks on
    a generation_failed row, the criteria PATCH commits first (recovering the
    question to pending_review), and the retry CAS must then miss because its
    source-state predicate no longer matches.
    """

    from datetime import datetime, timezone

    from app.features.question_library import repository
    from app.lib.database import session_scope

    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client)
        scene = helpers.create_scene(client)
        credential = helpers.create_credential(client, scene["id"])
        from app.lib.ai_runtime.adapters import FakeRubricGenerator

        failing = helpers.make_case("case-retry-race")
        failing["task_prompt"] = f"{FakeRubricGenerator.FAIL_MARKER} 生成失败的题目。"
        response = helpers.upload_batch(
            client, credential["token"], helpers.make_batch("cmd-retry-race", [failing])
        )
        question_id = response.json()["cases"][0]["question_id"]
        helpers.run_worker_until_idle()
        detail = client.get(f"/api/questions/{question_id}").json()
        assert detail["status"] == "generation_failed"
        revision = detail["content_revision"]

        # The teacher saves criteria first; the question recovers.
        patched = client.patch(
            f"/api/questions/{question_id}/criteria",
            json={
                "command_id": "criteria-before-retry",
                "content_revision": revision,
                "criteria": [
                    {
                        "id": "saved-rule",
                        "criterion": "老师先保存的评分标准，必须优先于迟到的重试。",
                        "pass_score": 6,
                    }
                ],
            },
        )
        assert patched.status_code == 200, patched.text

        # The trailing retry is rejected at the service gate...
        retry = client.post(
            f"/api/questions/{question_id}/generation-retry",
            json={"command_id": "retry-late", "content_revision": revision},
        )
        assert retry.status_code == 409
        assert retry.json()["error"]["code"] == "RETRY_NOT_AVAILABLE"

    # ...and at the CAS backstop: the source-state predicate misses.
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        raced = repository.update_fields(
            session,
            question_id,
            expected_revision=revision,
            now=now,
            expected_status="generation_failed",
            status="generating",
        )
    assert raced is None
    with session_scope() as session:
        record = repository.get_question(session, question_id)
    assert record is not None and record.status == "pending_review"
    assert record.criteria_confirmed is True


def test_regeneration_after_publish_keeps_delete_gate() -> None:
    """Editing materials of a published question un-confirms criteria but the
    ever-published delete protection survives."""

    clear_business_data()
    with TestClient(app) as client:
        question_id = _setup_pending_review(client)
        _confirm_criteria(client, question_id)
        published = _publish(client, question_id)

        save = client.post(
            f"/api/questions/{question_id}/save-regenerate",
            json={
                "command_id": "edit-after-publish",
                "content_revision": published["content_revision"],
                "task_prompt": "修改材料后重新生成。",
            },
        )
        assert save.status_code == 200
        helpers.run_worker_until_idle()
        detail = client.get(f"/api/questions/{question_id}").json()
        assert detail["status"] == "pending_review"
        assert detail["criteria_confirmed"] is False
        assert detail["next_action"] == "review_criteria"
        assert detail["delete_confirmation_required"] is True

        # Deleting it still requires the title confirmation.
        rejected = client.request(
            "DELETE",
            f"/api/questions/{question_id}",
            json={"command_id": "del-gate", "content_revision": detail["content_revision"]},
        )
        assert rejected.status_code == 422
        assert rejected.json()["error"]["code"] == "DELETE_CONFIRMATION_MISMATCH"
