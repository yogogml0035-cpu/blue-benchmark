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
    helpers.login_admin(client)
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

def test_generated_criteria_carry_complete_contract() -> None:
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
        materials = client.patch(
            f"/api/questions/{question_id}/materials",
            json={"content_revision": revision,
                  "task_prompt": "冻结期间的材料修改。"},
        )
        assert materials.status_code == 409
        assert materials.json()["error"]["code"] == "QUESTION_DELETING"
        regenerate = client.post(
            f"/api/questions/{question_id}/regenerate",
            json={"command_id": "g", "content_revision": revision},
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
        if job.last_error["code"] == "OPERATION_FAILED":
            # Generic worker errors must still be dispatched by job kind.
            assert "删除清理失败" in job.last_error["message"]


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
            f"/api/questions/{question_id}/regenerate",
            json={
                "command_id": "regen-events",
                "content_revision": detail["content_revision"],
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
        helpers.login_admin(client)
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


def test_failed_cleanup_retry_requeues_the_durable_job() -> None:
    """C1 regression: after a terminal cleanup failure, the UI retry (same
    DELETE endpoint) must actually requeue the job — never a placebo 202 that
    leaves the question frozen forever."""
    from app.features.question_library import run_streams
    from app.lib.operations import repository as ops_repository

    clear_business_data()
    with TestClient(app) as client:
        question_id = _upload_and_settle(client, "case-cleanup-retry")
        detail = client.get(f"/api/questions/{question_id}").json()
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
            json={"command_id": "del-retry", "content_revision": detail["content_revision"]},
        )
        assert accepted.status_code == 202
        operation_id = accepted.json()["operation_id"]

        from pydantic import SecretStr

        from app.lib.settings import settings

        original = settings.checkpoint_database_url
        try:
            settings.checkpoint_database_url = SecretStr(
                "postgresql://nobody@127.0.0.1:1/unreachable_db"
            )
            helpers.run_worker_until_idle()
            job = ops_repository.get(operation_id)
            assert job is not None and job.status == ops_repository.OperationJobStatus.failed

            # The teacher-visible retry: same DELETE with the same command id.
            retried = client.request(
                "DELETE",
                f"/api/questions/{question_id}",
                json={"command_id": "del-retry", "content_revision": detail["content_revision"]},
            )
            assert retried.status_code == 202
            assert retried.json()["operation_id"] == operation_id
            job = ops_repository.get(operation_id)
            assert job is not None
            assert job.status == ops_repository.OperationJobStatus.queued, (
                f"重试必须重新排队清理作业，实际状态 {job.status}"
            )
            assert job.attempts == 0  # fresh attempt budget, not yet claimed
        finally:
            settings.checkpoint_database_url = original


def test_midrun_material_edit_ends_old_operation_with_run_failed() -> None:
    """C-2 regression: when materials change mid-run, the old operation's log
    must end with a visible run_failed — never a completion for criteria that
    were not saved."""
    from app.lib.ai_runtime import adapters as adapter_module
    from app.lib.ai_runtime.adapters import (
        RubricGenerationInput,
        RunContext,
        RuntimeAdapters,
    )
    from app.features.question_library import service

    class SabotageGenerator(adapter_module.FakeRubricGenerator):
        uses_durable_runtime = False

        def __init__(self) -> None:
            self._sabotaged = False

        def generate(self, materials, *, context: RunContext, sink):
            if self._sabotaged:
                # Later rounds behave normally; the race is a one-shot event.
                return super().generate(materials, context=context, sink=sink)
            self._sabotaged = True
            # Teacher regenerates WHILE this run is in flight.
            service.regenerate(
                context.question_id,
                __import__(
                    "app.features.question_library.schemas", fromlist=["QuestionCommandRequest"]
                ).QuestionCommandRequest(
                    command_id="sabotage-regen",
                    content_revision=context.materials_revision,
                ),
            )
            return super().generate(materials, context=context, sink=sink)

    clear_business_data()
    previous = adapter_module.get_adapters()
    try:
        adapter_module.set_adapters(RuntimeAdapters(rubric_generator=SabotageGenerator()))
        with TestClient(app) as client:
            question_id = _upload_and_settle_first_attempt(client, "case-sabotage")
            # The worker keeps running the new job with the SAME adapters; let
            # it settle (the new round uses untouched materials and succeeds).
            helpers.run_worker_until_idle()
            detail = client.get(f"/api/questions/{question_id}").json()
            assert detail["status"] == "pending_review", detail
            old_operation = _all_operations(question_id)[0]
            new_operation = detail["last_operation_id"]
            assert old_operation != new_operation
            events = _events(client, question_id, old_operation)
            kinds = [e["kind"] for e in events["events"]]
            assert "run_completed" not in kinds, "被取代的运行不得记录完成事件"
            assert kinds[-1] == "run_failed"
            assert events["events"][-1]["detail"] == "superseded"
    finally:
        adapter_module.set_adapters(previous)


def _upload_and_settle_first_attempt(client: TestClient, case_id: str) -> str:
    """Upload and drive exactly ONE worker round (the sabotaged attempt)."""
    helpers.login_admin(client)
    scene = helpers.create_scene(client)
    credential = helpers.create_credential(client, scene["id"])
    response = helpers.upload_batch(
        client, credential["token"], helpers.make_batch(f"cmd-{case_id}", [helpers.make_case(case_id)])
    )
    assert response.status_code == 201, response.text
    question_id = response.json()["cases"][0]["question_id"]
    from app.lib.operations.worker import default_worker

    worker = default_worker()
    worker.run_once()
    return question_id


def _all_operations(question_id: str) -> list[str]:
    from sqlalchemy import select

    from app.lib.database.models import OperationJobRow

    with session_scope() as session:
        rows = session.execute(
            select(OperationJobRow.id).where(
                OperationJobRow.target_type == "eval_question",
                OperationJobRow.target_id == question_id,
            ).order_by(OperationJobRow.created_at)
        ).scalars().all()
    return list(rows)


def test_runtime_fingerprint_mismatch_refuses_resume() -> None:
    """M-1 regression: a thread registered under a different runtime identity
    must be refused loudly, never resumed on an incompatible graph contract."""
    from app.lib.ai_runtime import adapters as adapter_module
    from app.lib.ai_runtime.adapters import RuntimeAdapters
    from app.features.question_library import run_streams

    class DurableStub:
        uses_durable_runtime = True

        @property
        def harness_contract(self):
            return helpers.stub_harness_contract()

        def generate(self, materials, *, context, sink):
            raise AssertionError("fingerprint mismatch must fail before generation")

    clear_business_data()
    previous = adapter_module.get_adapters()
    try:
        adapter_module.set_adapters(RuntimeAdapters(rubric_generator=DurableStub()))
        with TestClient(app) as client:
            helpers.login_admin(client)
            scene = helpers.create_scene(client)
            credential = helpers.create_credential(client, scene["id"])
            response = helpers.upload_batch(
                client, credential["token"],
                helpers.make_batch("cmd-fp", [helpers.make_case("case-fp")]),
            )
            question_id = response.json()["cases"][0]["question_id"]
            # Pre-register the deterministic thread with the REAL materials
            # fingerprint but a STALE runtime identity, so only the runtime
            # check can fire.
            from sqlalchemy import select as _select

            from app.features.question_library import rubric_generation
            from app.lib.database.models import EvalQuestionRow

            with session_scope() as _session:
                _row = _session.execute(
                    _select(EvalQuestionRow).where(EvalQuestionRow.id == question_id)
                ).scalar_one()
                _materials = rubric_generation.build_generation_input(_row)
                _fp = rubric_generation.materials_fingerprint(_materials)
            run_streams.register_thread(
                run_streams.ThreadRegistration(
                    thread_id=run_streams.generation_thread_id(question_id, 1),
                    question_id=question_id,
                    operation_id="op-fp",
                    materials_revision=1,
                    materials_fingerprint=_fp,
                    runtime_fingerprint="stale-runtime-id",
                )
            )
            # No reachable checkpoint store: the incompatible thread cannot
            # be purged, so the attempt fails honestly with a retryable
            # infrastructure code (never a silent resume, never a fake success).
            from pydantic import SecretStr

            from app.lib.settings import settings as _settings

            original = _settings.checkpoint_database_url
            try:
                _settings.checkpoint_database_url = SecretStr(
                    "postgresql://nobody@127.0.0.1:1/unreachable_db"
                )
                helpers.run_worker_until_idle()
            finally:
                _settings.checkpoint_database_url = original
            detail = client.get(f"/api/questions/{question_id}").json()
            assert detail["status"] == "generation_failed"
            assert detail["last_error"]["code"] in (
                "CHECKPOINT_UNAVAILABLE", "CHECKPOINT_DSN_MISSING", "CHECKPOINT_KEY_MISSING",
            ), detail["last_error"]
    finally:
        adapter_module.set_adapters(previous)


def test_saved_citations_must_stay_verifiable() -> None:
    """M-2 regression: the edit path cannot launder a fabricated citation
    into a teacher-explicit claim."""
    clear_business_data()
    with TestClient(app) as client:
        question_id = _upload_and_settle(client, "case-citation")
        detail = client.get(f"/api/questions/{question_id}").json()
        criteria = json.loads(json.dumps(detail["criteria"]))

        # Forged locator: rejected.
        forged = json.loads(json.dumps(criteria))
        forged[0]["criterion_basis"]["claims"][0]["citation"] = {
            "locator": "bad_cases[9].feedback[3]",
            "quote": "任何文本",
        }
        response = client.patch(
            f"/api/questions/{question_id}/criteria",
            json={"command_id": "patch-forge-1", "content_revision": detail["content_revision"],
                  "criteria": forged},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "CITATION_INVALID"

        # Real locator, fabricated quote: rejected.
        wrong_quote = json.loads(json.dumps(criteria))
        wrong_quote[0]["criterion_basis"]["claims"][0]["citation"] = {
            "locator": "reference_answer",
            "quote": "材料中根本不存在的引文内容",
        }
        response = client.patch(
            f"/api/questions/{question_id}/criteria",
            json={"command_id": "patch-forge-2", "content_revision": detail["content_revision"],
                  "criteria": wrong_quote},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "CITATION_INVALID"

        # A teacher-edited claim quoting a REAL fragment still saves.
        answer = detail["reference_answer"]
        edited = json.loads(json.dumps(criteria))
        edited[0]["criterion_basis"]["claims"][0] = {
            "claim": "老师改写过的主张文本。",
            "kind": "ai_inferred",
            "citation": {"locator": "reference_answer", "quote": answer[:10]},
        }
        response = client.patch(
            f"/api/questions/{question_id}/criteria",
            json={"command_id": "patch-legit", "content_revision": detail["content_revision"],
                  "criteria": edited},
        )
        assert response.status_code == 200, response.text


def test_adapter_bounded_revision_round_fixes_bad_citation(monkeypatch) -> None:
    """A candidate with a fabricated citation gets ONE in-thread revision
    round; the revised candidate is re-validated and returned."""
    from langgraph.checkpoint.memory import InMemorySaver

    from app.lib.ai_runtime import deep_runtime as dr
    from app.lib.ai_runtime.adapters import (
        CriterionBasis,
        BasisClaim,
        DeepAgentRubricGenerator,
        PassScoreBasis,
        RubricGenerationFailure,
        RubricGenerationInput,
        RubricGenerationResult,
        CriterionDraft,
        RunContext,
        ScoreAnchor,
        SourceCitation,
    )
    from tests.test_deep_runtime import IDENTITY, ScriptedModel

    materials = RubricGenerationInput(
        task_prompt="任务材料。", reference_answer="老师认可的标准答案全文。"
    )

    def _result(quote: str) -> RubricGenerationResult:
        return RubricGenerationResult(criteria=[CriterionDraft(
            criterion="输出必须与标准答案一致，不得虚构材料之外的内容。",
            pass_score=6,
            score_anchors=[ScoreAnchor(score=6, description="与标准答案一致。")],
            criterion_basis=CriterionBasis(
                explanation="答案即基准。",
                claims=[BasisClaim(claim="答案基准。", kind="ai_inferred",
                                   citation=SourceCitation(locator="reference_answer", quote=quote))],
            ),
            pass_score_basis=PassScoreBasis(
                explained_score=6, explanation="一致即合格。",
                claims=[BasisClaim(claim="最低门槛。", kind="ai_inferred",
                                   citation=SourceCitation(locator="reference_answer", quote=quote))],
            ),
        )])

    calls = {"n": 0}

    def _fake_structured(agent, session):
        calls["n"] += 1
        # First read: fabricated quote. Second read (after revision): verbatim.
        return _result("编造的引文" if calls["n"] == 1 else "老师认可的标准答案全文。")

    monkeypatch.setattr(dr, "final_structured_response", _fake_structured)

    session = dr.CheckpointSession(None, InMemorySaver(), "t-revision")
    session._lock_held = True  # in-memory protocol test; no PG lock needed
    generator = DeepAgentRubricGenerator(
        model=ScriptedModel(messages=iter([
            __import__("langchain_core.messages", fromlist=["AIMessage"]).AIMessage(content="初稿完成。"),
            __import__("langchain_core.messages", fromlist=["AIMessage"]).AIMessage(content="修订完成。"),
        ])),
        identity=IDENTITY,
        contract=helpers.stub_harness_contract(),
        session_factory=lambda ctx: session,
    )
    sink = dr.ListSink()
    context = RunContext(
        thread_id="t-revision", operation_id="op-rev", attempt_number=1,
        question_id="q-rev", materials_revision=1, materials_fingerprint="f" * 64,
    )
    result = generator.generate(materials, context=context, sink=sink)
    assert calls["n"] == 2
    assert generator._revisions_used == 1
    assert result.criteria[0].criterion_basis.claims[0].citation.quote == "老师认可的标准答案全文。"
    assert any(e.stage == "revision_requested" for e in sink.events)

    # With revisions disabled the same failure surfaces immediately.
    calls["n"] = 0
    session2 = dr.CheckpointSession(None, InMemorySaver(), "t-revision-2")
    session2._lock_held = True
    strict = DeepAgentRubricGenerator(
        model=ScriptedModel(messages=iter([
            __import__("langchain_core.messages", fromlist=["AIMessage"]).AIMessage(content="初稿完成。"),
        ])),
        identity=IDENTITY,
        contract=helpers.stub_harness_contract(),
        session_factory=lambda ctx: session2,
        max_revisions=0,
    )
    context2 = RunContext(
        thread_id="t-revision-2", operation_id="op-rev2", attempt_number=1,
        question_id="q-rev2", materials_revision=1, materials_fingerprint="f" * 64,
    )
    import pytest as _pytest

    with _pytest.raises(RubricGenerationFailure) as exc_info:
        strict.generate(materials, context=context2, sink=dr.ListSink())
    assert exc_info.value.code == "AI_CITATION_INVALID"


def _audit_result(quote: str, locator: str = "reference_answer") -> "Any":
    from app.lib.ai_runtime.adapters import (
        BasisClaim,
        CriterionBasis,
        CriterionDraft,
        PassScoreBasis,
        RubricGenerationResult,
        ScoreAnchor,
        SourceCitation,
    )

    return RubricGenerationResult(criteria=[CriterionDraft(
        criterion="输出必须与标准答案一致，不得虚构材料之外的内容。",
        pass_score=6,
        score_anchors=[ScoreAnchor(score=6, description="与标准答案一致。")],
        criterion_basis=CriterionBasis(
            explanation="答案即基准。",
            claims=[BasisClaim(claim="答案基准。", kind="ai_inferred",
                               citation=SourceCitation(locator=locator, quote=quote))],
        ),
        pass_score_basis=PassScoreBasis(
            explained_score=6, explanation="一致即合格。",
            claims=[BasisClaim(claim="最低门槛。", kind="ai_inferred",
                               citation=SourceCitation(locator=locator, quote=quote))],
        ),
    )])


def test_repair_fixes_transcription_drift_without_revision_round() -> None:
    """Near-verbatim drift (one inserted char) is repaired deterministically:
    the stored quote becomes the exact source span, no model round needed."""
    from app.lib.ai_runtime.adapters import repair_citations, validate_result_citations

    texts = {
        "task_prompt": "任务材料。",
        "reference_answer": "老师认可的标准答案全文。成稿不应保留新闻稿的冗余段落。",
    }
    result = _audit_result("老师认可的标准答案的全文")  # 插入了一个「的」
    result, problems, repaired = repair_citations(result, texts)
    assert repaired == 2  # 同一条引文出现在两个 basis 中
    assert problems == []
    for basis in (result.criteria[0].criterion_basis, result.criteria[0].pass_score_basis):
        assert basis.claims[0].citation.quote == "老师认可的标准答案全文。"
    validate_result_citations(result, texts)  # strict gate now passes


def test_repair_never_flips_negation_polarity() -> None:
    """A single-character negation flip scores above the similarity threshold
    but must NOT be silently repaired into the opposite evidence."""
    from app.lib.ai_runtime.adapters import collect_citation_problems, repair_citations

    texts = {
        "task_prompt": "任务材料。",
        "reference_answer": "成稿不应保留新闻稿的冗余段落。",
    }
    result = _audit_result("成稿应保留新闻稿的冗余段落")  # 丢了一个「不」，极性反转
    result, problems, repaired = repair_citations(result, texts)
    assert repaired == 0
    assert len(problems) == 2
    # 最接近片段相似度虽高（>0.9），但否定词不一致，拒绝确定性替换。
    assert problems[0].expected == "成稿不应保留新闻稿的冗余段"
    assert problems[0].ratio >= 0.9
    assert result.criteria[0].criterion_basis.claims[0].citation.quote == "成稿应保留新闻稿的冗余段落"
    # The problem feedback hands the model the exact contradicting span.
    assert "成稿不应保留新闻稿的冗余段" in collect_citation_problems(result, texts)[0].describe()


def test_repair_repoints_unique_verbatim_locator_mixup() -> None:
    """A quote that is verbatim text of exactly ONE other material is a label
    mix-up: the locator is re-pointed, the quote stays untouched."""
    from app.lib.ai_runtime.adapters import repair_citations, validate_result_citations

    texts = {
        "task_prompt": "新闻稿正文片段A。",
        "reference_answer": "老师认可的标准答案全文。",
    }
    result = _audit_result("新闻稿正文片段A。", locator="reference_answer")
    result, problems, repaired = repair_citations(result, texts)
    assert repaired == 2
    assert problems == []
    citation = result.criteria[0].criterion_basis.claims[0].citation
    assert citation.locator == "task_prompt"
    assert citation.quote == "新闻稿正文片段A。"
    validate_result_citations(result, texts)


def test_ambiguous_multi_locator_match_goes_to_model_with_candidates() -> None:
    """When the quote is verbatim in MULTIPLE other materials, re-pointing
    would be an arbitrary attribution: keep it as a problem and list the
    candidates for the revision round."""
    from app.lib.ai_runtime.adapters import repair_citations

    texts = {
        "task_prompt": "同一篇新闻稿的句子。",
        "reference_examples[0]": "前言。同一篇新闻稿的句子。结尾。",
        "reference_answer": "老师认可的标准答案全文。",
    }
    result = _audit_result("同一篇新闻稿的句子。", locator="reference_answer")
    result, problems, repaired = repair_citations(result, texts)
    assert repaired == 0
    assert len(problems) == 2
    assert set(problems[0].alternates) == {"task_prompt", "reference_examples[0]"}
    described = problems[0].describe()
    assert "task_prompt" in described and "reference_examples[0]" in described
    # The citation is untouched for the model to fix.
    assert result.criteria[0].criterion_basis.claims[0].citation.locator == "reference_answer"


def test_validation_reports_every_problem_in_one_pass() -> None:
    """Fail-fast validation made single-round revision mathematically unable
    to converge; the gate must list ALL problems of the candidate set."""
    import pytest

    from app.lib.ai_runtime.adapters import validate_result_citations

    texts = {
        "task_prompt": "任务材料。",
        "reference_answer": "老师认可的标准答案全文。",
    }
    result = _audit_result("编造的引文甲")
    # Add two more bad citations of different kinds.
    from app.lib.ai_runtime.adapters import BasisClaim, SourceCitation

    result.criteria[0].criterion_basis.claims.append(
        BasisClaim(claim="另一条。", kind="ai_inferred",
                   citation=SourceCitation(locator="不存在的定位符", quote="任意引文"))
    )
    result.criteria[0].criterion_basis.claims.append(
        BasisClaim(claim="还有一条。", kind="ai_inferred",
                   citation=SourceCitation(locator="reference_answer", quote="编造的引文乙"))
    )
    with pytest.raises(RubricGenerationFailure) as exc_info:
        validate_result_citations(result, texts)
    message = exc_info.value.message
    assert exc_info.value.code == "AI_CITATION_INVALID"
    assert "claims[0]" in message and "claims[1]" in message and "claims[2]" in message
    assert "不存在的定位符" in message
    # Kind-specific guidance: fabricated quote vs unknown locator.
    assert "疑似虚构或改写过度" in message
    assert "本题任何材料中都不存在这段引文" in message


def test_generator_repairs_before_validation_and_skips_revision(monkeypatch) -> None:
    """Integration: a first-pass candidate whose quotes only drifted by
    transcription is repaired by the deterministic audit, so NO model
    revision round is spent and the run succeeds on the first read."""
    from langgraph.checkpoint.memory import InMemorySaver

    from app.lib.ai_runtime import deep_runtime as dr
    from app.lib.ai_runtime.adapters import DeepAgentRubricGenerator, RubricGenerationInput
    from tests.test_deep_runtime import IDENTITY, ScriptedModel

    materials = RubricGenerationInput(
        task_prompt="任务材料。", reference_answer="老师认可的标准答案全文。"
    )
    calls = {"n": 0}

    def _fake_structured(agent, session):
        calls["n"] += 1
        return _audit_result("老师认可的标准答案的全文")

    monkeypatch.setattr(dr, "final_structured_response", _fake_structured)
    session = dr.CheckpointSession(None, InMemorySaver(), "t-repair")
    session._lock_held = True
    generator = DeepAgentRubricGenerator(
        model=ScriptedModel(messages=iter([
            __import__("langchain_core.messages", fromlist=["AIMessage"]).AIMessage(content="初稿完成。"),
        ])),
        identity=IDENTITY,
        contract=helpers.stub_harness_contract(),
        session_factory=lambda ctx: session,
    )
    sink = dr.ListSink()
    context = RunContext(
        thread_id="t-repair", operation_id="op-rep", attempt_number=1,
        question_id="q-rep", materials_revision=1, materials_fingerprint="f" * 64,
    )
    result = generator.generate(materials, context=context, sink=sink)
    assert calls["n"] == 1  # no revision round
    assert generator._revisions_used == 0
    assert result.criteria[0].criterion_basis.claims[0].citation.quote == "老师认可的标准答案全文。"
    assert any(e.stage == "citations_repaired" for e in sink.events)
    assert not any(e.stage == "revision_requested" for e in sink.events)
