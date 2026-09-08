"""C4 system fault-injection regressions.

Extends the C3 baseline with the design-matrix scenarios that were not yet
locked by tests: lease-loss late writers, cross-question isolation at the
business layer, multi-thread deletion history with a partial-cleanup crash,
and late SSE subscription replay. Real-provider restart recovery and
mid-generation late-join are covered by the extended web acceptance runner.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.lib.ai_runtime import adapters as adapter_module
from app.lib.ai_runtime.adapters import RunContext, RuntimeAdapters
from app.lib.database import clear_business_data, session_scope
from app.main import app
from tests import helpers


# ---------------------------------------------------------------------------
# Lease loss: a writer that no longer owns the job must not commit or complete
# ---------------------------------------------------------------------------

def test_lease_lost_writer_cannot_commit_or_emit_completion() -> None:
    class StealingGenerator(adapter_module.FakeRubricGenerator):
        uses_durable_runtime = False

        def generate(self, materials, *, context: RunContext, sink):
            result = super().generate(materials, context=context, sink=sink)
            # Simulate the lease expiring and another worker taking the job
            # while this writer was inside the model call.
            from sqlalchemy import update as sa_update

            from app.lib.database.models import OperationJobRow

            with session_scope() as session:
                session.execute(
                    sa_update(OperationJobRow)
                    .where(OperationJobRow.id == context.operation_id)
                    .values(worker_id="worker-usurper")
                )
            return result

    clear_business_data()
    previous = adapter_module.get_adapters()
    try:
        adapter_module.set_adapters(RuntimeAdapters(rubric_generator=StealingGenerator()))
        with TestClient(app) as client:
            helpers.login_admin(client)
            scene = helpers.create_scene(client)
            credential = helpers.create_credential(client, scene["id"])
            response = helpers.upload_batch(
                client, credential["token"],
                helpers.make_batch("cmd-lease", [helpers.make_case("case-lease")]),
            )
            question_id = response.json()["cases"][0]["question_id"]
            from app.lib.operations.worker import default_worker

            worker = default_worker()
            worker.run_once()

            detail = client.get(f"/api/questions/{question_id}").json()
            # The late writer committed NOTHING: still generating, no criteria.
            assert detail["status"] == "generating", detail
            assert detail["criteria"] is None

            from app.features.question_library import run_streams

            with session_scope() as session:
                from sqlalchemy import select

                from app.lib.database.models import OperationJobRow

                job = session.execute(
                    select(OperationJobRow).where(
                        OperationJobRow.target_type == "eval_question",
                        OperationJobRow.target_id == question_id,
                    )
                ).scalars().first()
            assert job.worker_id == "worker-usurper", "测试前提：所有权已被夺走"
            events = run_streams.read_events(question_id, job.id)
            kinds = [e.kind for e in events]
            assert "run_completed" not in kinds, "失租写者不得发出完成事件"
            # The old worker's own fail/supersede attempts are refused too.
            from app.lib.operations import repository as ops_repository

            with pytest.raises(ValueError):
                ops_repository.fail(
                    job.id, "not-the-owner", {"code": "X", "message": "x"}, retryable=False
                )
    finally:
        adapter_module.set_adapters(previous)


# ---------------------------------------------------------------------------
# Cross-question isolation at the business layer
# ---------------------------------------------------------------------------

def test_generation_inputs_never_cross_questions() -> None:
    seen: dict[str, str] = {}

    class RecordingGenerator(adapter_module.FakeRubricGenerator):
        # Durable registration path: the handler registers per-question
        # threads (business DB only), making the disjointness assertion below
        # a real check instead of a vacuous one. The fake generate() never
        # opens a checkpoint session, so no PG is required here.
        uses_durable_runtime = True

        @property
        def harness_contract(self):
            return helpers.stub_harness_contract()

        def generate(self, materials, *, context: RunContext, sink):
            blob = json.dumps(materials.model_dump(), ensure_ascii=False)
            seen[context.question_id] = blob
            return super().generate(materials, context=context, sink=sink)

    clear_business_data()
    previous = adapter_module.get_adapters()
    try:
        adapter_module.set_adapters(RuntimeAdapters(rubric_generator=RecordingGenerator()))
        with TestClient(app) as client:
            helpers.login_admin(client)
            scene = helpers.create_scene(client)
            credential = helpers.create_credential(client, scene["id"])
            case_a = helpers.make_case("case-iso-a")
            case_a["reference_answer"] = "A 题独有的标准答案标记 MARKER-A-91。"
            case_b = helpers.make_case("case-iso-b")
            case_b["reference_answer"] = "B 题独有的标准答案标记 MARKER-B-92。"
            response = helpers.upload_batch(
                client, credential["token"],
                helpers.make_batch("cmd-iso", [case_a, case_b]),
            )
            ids = {c["client_case_id"]: c["question_id"] for c in response.json()["cases"]}
            helpers.run_worker_until_idle()

            assert len(seen) == 2
            blob_a = seen[ids["case-iso-a"]]
            blob_b = seen[ids["case-iso-b"]]
            assert "MARKER-A-91" in blob_a and "MARKER-B-92" not in blob_a
            assert "MARKER-B-92" in blob_b and "MARKER-A-91" not in blob_b
            # Threads are per-question and never shared.
            from app.features.question_library import run_streams

            threads_a = run_streams.list_question_threads(ids["case-iso-a"])
            threads_b = run_streams.list_question_threads(ids["case-iso-b"])
            assert threads_a and threads_b, "durable 路径必须登记每题线程"
            assert not (set(threads_a) & set(threads_b))
            assert all(ids["case-iso-a"] in t for t in threads_a)
            assert all(ids["case-iso-b"] in t for t in threads_b)
    finally:
        adapter_module.set_adapters(previous)


# ---------------------------------------------------------------------------
# Late SSE subscription: full replay + terminal done after completion
# ---------------------------------------------------------------------------

def test_late_sse_subscription_replays_full_log_and_terminates() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.login_admin(client)
        scene = helpers.create_scene(client)
        credential = helpers.create_credential(client, scene["id"])
        response = helpers.upload_batch(
            client, credential["token"],
            helpers.make_batch("cmd-late-sse", [helpers.make_case("case-late-sse")]),
        )
        question_id = response.json()["cases"][0]["question_id"]
        helpers.run_worker_until_idle()
        detail = client.get(f"/api/questions/{question_id}").json()
        assert detail["status"] == "pending_review"
        operation_id = detail["last_operation_id"]

        snapshot = client.get(
            f"/api/questions/{question_id}/runs/{operation_id}/events"
        ).json()
        assert snapshot["events"]

        # A subscriber arriving AFTER completion still receives the complete
        # log (from sequence 0) and a terminal done frame — nothing is lost
        # by not having been connected live.
        with client.stream(
            "GET",
            f"/api/questions/{question_id}/runs/{operation_id}/events/stream",
        ) as stream:
            payload = "".join(chunk for chunk in stream.iter_text())
        frames = [
            json.loads(line[len("data: "):])
            for line in payload.splitlines()
            if line.startswith("data: ")
        ]
        event_frames = [f for f in frames if f["type"] == "event"]
        assert len(event_frames) == len(snapshot["events"])
        assert [f["sequence"] for f in event_frames] == [
            e["sequence"] for e in snapshot["events"]
        ]
        assert frames[-1]["type"] == "done"
        assert frames[-1]["status"] == "pending_review"

        # Cursor semantics: subscribing from the last sequence yields no
        # duplicate events, only the terminal frame.
        last = snapshot["last_sequence"]
        with client.stream(
            "GET",
            f"/api/questions/{question_id}/runs/{operation_id}/events/stream",
            params={"after_sequence": last},
        ) as stream:
            payload2 = "".join(chunk for chunk in stream.iter_text())
        frames2 = [
            json.loads(line[len("data: "):])
            for line in payload2.splitlines()
            if line.startswith("data: ")
        ]
        assert [f["type"] for f in frames2] == ["done"]


# ---------------------------------------------------------------------------
# Multi-thread deletion history with a partial-cleanup crash (PG-gated)
# ---------------------------------------------------------------------------

def test_partial_cleanup_crash_resumes_and_finishes_all_threads(pg_business_env, monkeypatch) -> None:
    """Two regeneration rounds leave TWO threads; cleanup deletes the first,
    crashes on the second, and the retried job finishes the job idempotently —
    zero residue for BOTH threads, no premature success."""
    from app.features.question_library import run_streams
    from app.lib.ai_runtime import deep_runtime as dr
    from app.lib.operations import repository as ops_repository
    from tests.test_question_runtime_postgres import _PgStubGenerator, _clean_from_dsn

    dsn = pg_business_env
    previous = adapter_module.get_adapters()
    question_id = None
    try:
        with TestClient(app) as client:
            helpers.login_admin(client)
            scene = helpers.create_scene(client)
            credential = helpers.create_credential(client, scene["id"])
            response = helpers.upload_batch(
                client, credential["token"],
                helpers.make_batch("cmd-multi-del", [helpers.make_case("case-multi-del")]),
            )
            question_id = response.json()["cases"][0]["question_id"]

            # Round 1 generation on the real checkpoint DB.
            gen1 = _PgStubGenerator(dsn)
            adapter_module.set_adapters(RuntimeAdapters(rubric_generator=gen1))
            helpers.run_worker_until_idle()
            detail = client.get(f"/api/questions/{question_id}").json()
            assert detail["status"] == "pending_review"
            thread_r1 = f"qgen-{question_id}-r1"

            # Round 2: regeneration creates revision 2 -> a SECOND thread.
            regen = client.post(
                f"/api/questions/{question_id}/regenerate",
                json={
                    "command_id": "regen-multi",
                    "content_revision": detail["content_revision"],
                },
            )
            assert regen.status_code == 200, regen.text
            gen2 = _PgStubGenerator(dsn)
            adapter_module.set_adapters(RuntimeAdapters(rubric_generator=gen2))
            helpers.run_worker_until_idle()
            detail = client.get(f"/api/questions/{question_id}").json()
            assert detail["status"] == "pending_review"
            thread_r2 = f"qgen-{question_id}-r2"
            assert set(run_streams.list_question_threads(question_id)) == {thread_r1, thread_r2}

            # Accept deletion, then make cleanup crash AFTER the first thread.
            accepted = client.request(
                "DELETE",
                f"/api/questions/{question_id}",
                json={"command_id": "del-multi", "content_revision": detail["content_revision"]},
            )
            assert accepted.status_code == 202
            operation_id = accepted.json()["operation_id"]

            real_delete = dr.delete_thread_data
            state = {"armed": True}

            def flaky_delete(session):
                # Persistent failure on r2 while armed: r1 is deleted every
                # pass (idempotent), r2 never completes until disarmed — so
                # the attempt budget exhausts into a TERMINAL failed cleanup
                # instead of self-healing inside run_worker_until_idle.
                if session.thread_id == thread_r2 and state["armed"]:
                    raise dr.DeepRuntimeError(
                        "SIMULATED_CLEANUP_CRASH", "模拟清理中断。", retryable=True
                    )
                return real_delete(session)

            monkeypatch.setattr(dr, "delete_thread_data", flaky_delete)
            try:
                helpers.run_worker_until_idle()
                frozen = client.get(f"/api/questions/{question_id}").json()
                # NOT deleted: cleanup crashed, question stays frozen, failure
                # is visible — never a premature success.
                assert frozen["status"] == "deleting"
                assert frozen["deletion"]["phase"] == "failed"
                assert frozen["deletion"]["error"]["code"] == "SIMULATED_CLEANUP_CRASH"
                job = ops_repository.get(operation_id)
                assert job.status == ops_repository.OperationJobStatus.failed
                # r1 was cleaned on the way; r2 still has residue (not yet deleted).
                import psycopg as _psycopg

                with _psycopg.connect(dsn, autocommit=True) as conn:
                    r2_residue = dr.thread_data_residue(conn, thread_r2)
                assert any(v > 0 for v in r2_residue.values()), "崩溃点之前的线程不应被提前清空"
            finally:
                state["armed"] = False
                monkeypatch.setattr(dr, "delete_thread_data", real_delete)

            # Teacher retry: the SAME endpoint requeues; cleanup completes
            # idempotently (r1 already gone) and deletes r2.
            retried = client.request(
                "DELETE",
                f"/api/questions/{question_id}",
                json={"command_id": "del-multi", "content_revision": detail["content_revision"]},
            )
            assert retried.status_code == 202
            helpers.run_worker_until_idle()
            assert client.get(f"/api/questions/{question_id}").status_code == 404

            # Zero residue for BOTH threads in the checkpoint store, and no
            # business-side leftovers.
            import psycopg

            with psycopg.connect(dsn, autocommit=True) as conn:
                for thread in (thread_r1, thread_r2):
                    residue = dr.thread_data_residue(conn, thread)
                    assert all(v == 0 for v in residue.values()), (thread, residue)
            from sqlalchemy import select

            from app.lib.database.models import QuestionRunEventRow, QuestionRunThreadRow

            with session_scope() as session:
                assert session.execute(
                    select(QuestionRunThreadRow).where(
                        QuestionRunThreadRow.question_id == question_id
                    )
                ).scalars().all() == []
                assert session.execute(
                    select(QuestionRunEventRow).where(
                        QuestionRunEventRow.question_id == question_id
                    )
                ).scalars().all() == []
    finally:
        adapter_module.set_adapters(previous)
        if question_id:
            _clean_from_dsn(dsn, f"qgen-{question_id}-r1")
            _clean_from_dsn(dsn, f"qgen-{question_id}-r2")


# Fixture import for the PG-gated test (same exclusive test database as C3).
from tests.test_question_runtime_postgres import pg_business_env  # noqa: E402,F401
