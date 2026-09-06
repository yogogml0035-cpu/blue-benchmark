"""C3 business contract tests: complete criteria editing, deletion freeze,
persisted run events, SSE replay and completion gating (fake-mode, SQLite).

Durable-runtime integration (real PostgreSQL checkpoints, resume across
restarts, cross-store deletion) lives in test_question_runtime_postgres.py.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from app.lib.ai_runtime.adapters import (
    FakeRubricGenerator,
    RubricGenerationFailure,
    RunContext,
)
from app.lib.database import clear_business_data, session_scope
from app.lib.database.models import EvalQuestionRow, OperationJobRow, QuestionRunEventRow
from app.main import app
from tests import helpers


def _upload_and_settle(client: TestClient, case_id: str = "case-rt") -> str:
    helpers.register_admin(client)
    scene = helpers.create_scene(client)
    credential = helpers.create_credential(client, scene["id"])
    response = helpers.upload_batch(
        client, credential["token"], helpers.make_batch(f"cmd-{case_id}", [helpers.make_case(case_id)])
    )
    assert response.status_code == 201, response.text
    question_id = response.json()["cases"][0]["question_id"]
    helpers.run_worker_until_idle()
    return question_id


def _events(client: TestClient, question_id: str, operation_id: str) -> dict:
    response = client.get(f"/api/questions/{question_id}/runs/{operation_id}/events")
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Complete criteria contract: teacher editing
# ---------------------------------------------------------------------------

def test_generated_criteria_carry_complete_contract(client=None) -> None:
    clear_business_data()
    with TestClient(app) as client:
        question_id = _upload_and_settle(client)
        detail = client.get(f"/api/questions/{question_id}").json()
        for item in detail["criteria"]:
            assert item["score_anchors"]
            assert item["criterion_basis"]["claims"]
            assert item["pass_score_basis"]["explained_score"] == item["pass_score"]
        # The public event log recorded the fake run and completion came only
        # after the business save.
        with session_scope() as session:
            row = session.get(EvalQuestionRow, question_id)
            active = row.active_operation_id
        events = _events(client, question_id, _generation_operation(question_id))
        kinds = [event["kind"] for event in events["events"]]
        assert "run_completed" in kinds
        assert kinds[-1] == "run_completed"
        assert "stage" in kinds


def _generation_operation(question_id: str) -> str:
    from sqlalchemy import select

    with session_scope() as session:
        row = session.execute(
            select(OperationJobRow).where(
                OperationJobRow.target_type == "eval_question",
                OperationJobRow.target_id == question_id,
            )
        ).scalars().first()
    assert row is not None
    return row.id


def test_teacher_may_save_unanchored_integer_and_keeps_bases() -> None:
    """Changing the pass score to an integer WITHOUT an anchor must save;
    anchors/bases are preserved untouched (no auto-rewrite, no whitelist)."""
    clear_business_data()
    with TestClient(app) as client:
        question_id = _upload_and_settle(client, "case-edit")
        detail = client.get(f"/api/questions/{question_id}").json()
        criteria = detail["criteria"]
        target = criteria[0]
        assert 5 not in [a["score"] for a in target["score_anchors"]], (
            "test premise: the fake anchors must not already contain 5"
        )
        target["pass_score"] = 5  # unanchored integer on purpose
        response = client.patch(
            f"/api/questions/{question_id}/criteria",
            json={
                "command_id": "patch-unanchored",
                "content_revision": detail["content_revision"],
                "criteria": criteria,
            },
        )
        assert response.status_code == 200, response.text
        saved = response.json()["criteria"][0]
        assert saved["pass_score"] == 5
        # The basis still explains the ORIGINAL suggested score: the UI flags
        # the mismatch, the backend never rewrites it silently.
        assert saved["pass_score_basis"]["explained_score"] != 5
        assert saved["score_anchors"] == target["score_anchors"]
        assert response.json()["criteria_confirmed"] is True


def test_score_validation_bounds_still_apply() -> None:
    clear_business_data()
    with TestClient(app) as client:
        question_id = _upload_and_settle(client, "case-bounds")
        detail = client.get(f"/api/questions/{question_id}").json()
        criteria = detail["criteria"]
        for bad_score in (11, -1, 5.5):
            broken = json.loads(json.dumps(criteria))
            broken[0]["pass_score"] = bad_score
            response = client.patch(
                f"/api/questions/{question_id}/criteria",
                json={
                    "command_id": f"patch-bad-{bad_score}",
                    "content_revision": detail["content_revision"],
                    "criteria": broken,
                },
            )
            assert response.status_code == 422, (bad_score, response.text)


def test_manual_criterion_may_have_explicitly_empty_auxiliaries() -> None:
    clear_business_data()
    with TestClient(app) as client:
        question_id = _upload_and_settle(client, "case-manual")
        detail = client.get(f"/api/questions/{question_id}").json()
        criteria = detail["criteria"] + [
            {
                "id": "manual-1",
                "criterion": "老师手工新增的完整可执行评判标准。",
                "pass_score": 6,
                "score_anchors": [],
                "criterion_basis": None,
                "pass_score_basis": None,
            }
        ]
        response = client.patch(
            f"/api/questions/{question_id}/criteria",
            json={
                "command_id": "patch-manual",
                "content_revision": detail["content_revision"],
                "criteria": criteria,
            },
        )
        assert response.status_code == 200, response.text
        manual = next(c for c in response.json()["criteria"] if c["id"] == "manual-1")
        assert manual["score_anchors"] == []
        assert manual["criterion_basis"] is None
        assert manual["pass_score_basis"] is None


# ---------------------------------------------------------------------------
# Deletion freeze and cleanup receipts
# ---------------------------------------------------------------------------

def test_deleting_freeze_blocks_every_write_path() -> None:
    from app.features.question_library import deletion
    from app.lib.operations import repository as ops_repository

    clear_business_data()
    with TestClient(app) as client:
        question_id = _upload_and_settle(client, "case-freeze")
        detail = client.get(f"/api/questions/{question_id}").json()
        revision = detail["content_revision"]
        accepted = client.request(
            "DELETE",
            f"/api/questions/{question_id}",
            json={"command_id": "del-freeze", "content_revision": revision},
        )
        assert accepted.status_code == 202
        operation_id = accepted.json()["operation_id"]

        # Freeze is visible in the detail projection.
        frozen = client.get(f"/api/questions/{question_id}").json()
        assert frozen["status"] == "deleting"
        assert frozen["next_action"] == "wait_for_deletion"
        assert frozen["deletion"] == {
            "operation_id": operation_id, "phase": "queued", "error": None,
        }

        # Every write path is refused while frozen.
        title = client.patch(
            f"/api/questions/{question_id}/title",
            json={"command_id": "t", "content_revision": revision, "title": "新标题"},
        )
        assert title.status_code == 409 and title.json()["error"]["code"] == "QUESTION_DELETING"
        publish = client.post(
            f"/api/questions/{question_id}/publication",
            json={"command_id": "p", "content_revision": revision},
        )
        assert publish.status_code == 409 and publish.json()["error"]["code"] == "QUESTION_DELETING"
        retry = client.post(
            f"/api/questions/{question_id}/generation-retry",
            json={"command_id": "r", "content_revision": revision},
        )
        assert retry.status_code == 409 and retry.json()["error"]["code"] == "QUESTION_DELETING"
        criteria = client.patch(
            f"/api/questions/{question_id}/criteria",
            json={"command_id": "c", "content_revision": revision,
                  "criteria": frozen["criteria"]},
        )
        assert criteria.status_code == 409 and criteria.json()["error"]["code"] == "QUESTION_DELETING"
        regenerate = client.post(
            f"/api/questions/{question_id}/save-regenerate",
            json={"command_id": "g", "content_revision": revision,
                  "task_prompt": "冻结期间的材料修改。"},
        )
        assert regenerate.status_code == 409
        assert regenerate.json()["error"]["code"] == "QUESTION_DELETING"
        events = client.get(f"/api/questions/{question_id}/runs/{operation_id}/events")
        assert events.status_code in (404, 409)

        # Idempotent re-acceptance returns the SAME operation.
        again = client.request(
            "DELETE",
            f"/api/questions/{question_id}",
            json={"command_id": "del-freeze-2", "content_revision": revision},
        )
        assert again.status_code == 202
        assert again.json()["operation_id"] == operation_id

        # Drive cleanup; the question disappears and the receipt survives.
        helpers.run_worker_until_idle()
        assert client.get(f"/api/questions/{question_id}").status_code == 404
        job = ops_repository.get(operation_id)
        assert job is not None and job.status == ops_repository.OperationJobStatus.succeeded

        # A late replay of the accepted delete is a plain 404, never a
        # resurrection.
        replay = client.request(
            "DELETE",
            f"/api/questions/{question_id}",
            json={"command_id": "del-freeze", "content_revision": revision},
        )
        assert replay.status_code == 404


def test_cleanup_failure_is_visible_and_retryable_not_generation_failure() -> None:
    """When registered threads exist but the checkpoint store is unreachable,
    cleanup fails loudly (retryable), the question stays frozen with a visible
    error, and nothing is projected as a generation failure."""
    from app.features.question_library import run_streams

    clear_business_data()
    with TestClient(app) as client:
        question_id = _upload_and_settle(client, "case-cleanup-fail")
        detail = client.get(f"/api/questions/{question_id}").json()
        # Simulate a durable generation history: one registered thread.
        run_streams.register_thread(
            run_streams.ThreadRegistration(
                thread_id=f"qgen-{question_id}-r{detail['content_revision']}",
                question_id=question_id,
                operation_id=_generation_operation(question_id),
                materials_revision=detail["content_revision"],
                materials_fingerprint="f" * 64,
                runtime_fingerprint="r" * 16,
            )
        )
        accepted = client.request(
            "DELETE",
            f"/api/questions/{question_id}",
            json={"command_id": "del-fail", "content_revision": detail["content_revision"]},
        )
        assert accepted.status_code == 202
        operation_id = accepted.json()["operation_id"]

        # Point the checkpoint config at an unreachable port so cleanup cannot
        # silently succeed against whatever DSN the environment carries (the
        # override also guarantees this test never touches a real checkpoint
        # database).
        from app.lib.settings import settings

        original = settings.checkpoint_database_url
        try:
            from pydantic import SecretStr

            settings.checkpoint_database_url = SecretStr(
                "postgresql://nobody@127.0.0.1:1/unreachable_db"
            )
            helpers.run_worker_until_idle()
        finally:
            settings.checkpoint_database_url = original

        frozen = client.get(f"/api/questions/{question_id}").json()
        assert frozen["status"] == "deleting"
        assert frozen["deletion"]["operation_id"] == operation_id
        assert frozen["deletion"]["phase"] in ("queued", "failed")
        # The failure is a CLEANUP error, never a generation failure projection.
        assert frozen["last_error"] is None or frozen["last_error"].get("code") != "GENERATION_FAILED"
        from app.lib.operations import repository as ops_repository

        job = ops_repository.get(operation_id)
        assert job is not None
        assert job.last_error is not None
        assert job.last_error["code"] in ("CHECKPOINT_DSN_MISSING", "THREAD_LOCK_BUSY",
                                          "THREAD_CLEANUP_INCOMPLETE", "OPERATION_FAILED")
        assert "评分维度生成失败" not in str(job.last_error.get("message", ""))


# ---------------------------------------------------------------------------
# Run events, replay and superseded guards
# ---------------------------------------------------------------------------

def test_events_survive_reload_and_superseded_runs_are_rejected() -> None:
    clear_business_data()
    with TestClient(app) as client:
        question_id = _upload_and_settle(client, "case-events")
        operation_id = _generation_operation(question_id)
        page = _events(client, question_id, operation_id)
        assert page["events"], "the fake run must persist public events"
        assert page["status"] == "pending_review"
        # Cursor restore: after_sequence replays nothing new and never errors.
        tail = _events(client, question_id, operation_id)
        last = tail["last_sequence"]
        page2 = client.get(
            f"/api/questions/{question_id}/runs/{operation_id}/events",
            params={"after_sequence": last},
        ).json()
        assert page2["events"] == []
        assert page2["last_sequence"] == last
        # An unknown operation id has no events but is not an error.
        unknown = client.get(f"/api/questions/{question_id}/runs/no-such-op/events")
        assert unknown.status_code == 200 and unknown.json()["events"] == []
        # A superseded generation operation is refused while a new one is active.
        detail = client.get(f"/api/questions/{question_id}").json()
        regenerate = client.post(
            f"/api/questions/{question_id}/save-regenerate",
            json={
                "command_id": "regen-events",
                "content_revision": detail["content_revision"],
                "task_prompt": detail["task_prompt"] + " 修改材料触发重生成。",
            },
        )
        assert regenerate.status_code == 200
        new_operation = regenerate.json()["operation_id"]
        superseded = client.get(
            f"/api/questions/{question_id}/runs/{operation_id}/events"
        )
        assert superseded.status_code == 409
        assert superseded.json()["error"]["code"] == "OPERATION_SUPERSEDED"
        helpers.run_worker_until_idle()
        fresh = _events(client, question_id, new_operation)
        assert fresh["events"]


def test_sse_stream_delivers_persisted_events_and_terminates() -> None:
    clear_business_data()
    with TestClient(app) as client:
        question_id = _upload_and_settle(client, "case-sse")
        operation_id = _generation_operation(question_id)
        with client.stream(
            "GET", f"/api/questions/{question_id}/runs/{operation_id}/events/stream"
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            payload = "".join(chunk for chunk in response.iter_text())
        lines = [l for l in payload.splitlines() if l.startswith("data: ")]
        assert lines, "SSE must deliver the persisted events"
        events = [json.loads(l[len("data: "):]) for l in lines]
        kinds = [e["type"] for e in events]
        assert "event" in kinds
        assert kinds[-1] == "done"
        assert events[-1]["status"] == "pending_review"


def test_failed_generation_records_run_failed_event() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client)
        scene = helpers.create_scene(client)
        credential = helpers.create_credential(client, scene["id"])
        case = helpers.make_case("case-fail-ev")
        case["task_prompt"] = f"{FakeRubricGenerator.FAIL_MARKER} 生成失败的题目。"
        response = helpers.upload_batch(
            client, credential["token"], helpers.make_batch("cmd-fail-ev", [case])
        )
        question_id = response.json()["cases"][0]["question_id"]
        helpers.run_worker_until_idle()
        detail = client.get(f"/api/questions/{question_id}").json()
        assert detail["status"] == "generation_failed"
        operation_id = _generation_operation(question_id)
        page = _events(client, question_id, operation_id)
        kinds = [e["kind"] for e in page["events"]]
        assert "run_failed" in kinds
        assert "run_completed" not in kinds
