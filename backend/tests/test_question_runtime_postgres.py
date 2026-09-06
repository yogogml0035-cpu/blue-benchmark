"""Business-chain durability tests on the task-exclusive PostgreSQL database.

Proves, through the REAL worker handler and business API (not just runtime
primitives): thread registration, checkpoint-backed resume across a simulated
worker crash without duplicated initial input, persisted public events across
attempts, and complete cross-store deletion (business rows + checkpoint rows)
with zero residue.

Gated like the C2 primitive tests: skips loudly without PostgreSQL and fails
under RUNTIME_PG_REQUIRED=1. Never touches skill_eval / skill_eval_checkpoint.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest
from fastapi.testclient import TestClient

from app.lib.ai_runtime import deep_runtime as dr
from app.lib.ai_runtime.adapters import (
    CriterionBasis,
    BasisClaim,
    PassScoreBasis,
    RubricGenerationFailure,
    RubricGenerationResult,
    CriterionDraft,
    RuntimeAdapters,
    ScoreAnchor,
    SourceCitation,
    get_adapters,
    set_adapters,
)
from app.lib.database import clear_business_data, session_scope
from app.lib.database.models import QuestionRunEventRow, QuestionRunThreadRow
from app.lib.settings import settings
from app.main import app
from tests import helpers
from tests.test_deep_runtime import IDENTITY, ScriptedModel
from tests.test_deep_runtime_postgres import TEST_DB_NAME, _clean, _test_dsn

pytest.importorskip("psycopg")

from langchain_core.messages import AIMessage  # noqa: E402


def _fixed_result(materials) -> RubricGenerationResult:
    quote = materials.reference_answer.strip()[:30]
    claims = [
        BasisClaim(
            claim="标准答案给出了合格输出的基准。",
            kind="ai_inferred",
            citation=SourceCitation(locator="reference_answer", quote=quote),
        )
    ]
    return RubricGenerationResult(
        criteria=[
            CriterionDraft(
                criterion="输出必须与标准答案的事实与结构保持一致，不得虚构材料之外的内容。",
                pass_score=6,
                score_anchors=[
                    ScoreAnchor(score=4, description="存在事实偏差或结构缺失。"),
                    ScoreAnchor(score=6, description="事实与结构均与标准答案一致。"),
                ],
                criterion_basis=CriterionBasis(
                    explanation="标准答案是老师认可的正向依据。", claims=claims
                ),
                pass_score_basis=PassScoreBasis(
                    explained_score=6, explanation="一致即达到最低要求。", claims=claims
                ),
            )
        ]
    )


class _PgStubGenerator:
    """Durable generator on the real PG saver with scripted model rounds.

    ``crash_after`` simulates a worker death mid-run (retryable failure after
    real checkpoint writes); the resume attempt records how it was invoked so
    the test can assert inputs=None semantics.
    """

    uses_durable_runtime = True

    def __init__(self, dsn: str, *, crash_after: bool = False,
                 crash_after_complete: bool = False) -> None:
        self._dsn = dsn
        self._crash = crash_after
        self._crash_after_complete = crash_after_complete
        self.observations: list[dict[str, Any]] = []

    def _cfg(self) -> Any:
        from pydantic import SecretStr

        class _Cfg:
            checkpoint_database_url = SecretStr(self._dsn)
            langgraph_aes_key = settings.langgraph_aes_key

        return _Cfg()

    def generate(self, materials, *, context, sink) -> RubricGenerationResult:
        session = dr.open_session(context.thread_id, self._cfg())
        try:
            if self._crash:
                script = [
                    AIMessage(
                        content="",
                        tool_calls=[{
                            "name": "write_file",
                            "args": {"file_path": "/workspace/progress.md",
                                     "content": "已完成材料核查。"},
                            "id": "w1", "type": "tool_call",
                        }],
                    ),
                    AIMessage(content="不会到达"),
                ]
            else:
                script = [AIMessage(content="候选集已完成。")]
            agent = dr.build_restricted_agent(
                ScriptedModel(messages=iter(script)),
                IDENTITY,
                system_prompt="业务集成测试",
                # The crash mode caps model calls at 1 so the run dies right
                # after the first tool round — a genuinely incomplete thread
                # with real persisted checkpoints.
                budget=dr.RuntimeBudget(max_model_calls=1 if self._crash else 24),
                counters=dr.BudgetCounters(),
                sink=sink,
                checkpointer=session.saver,
            )
            state_kind = dr.classify_thread_state(agent, session.thread_config())
            inputs: Any
            if state_kind == "new":
                inputs = {
                    "messages": [{"role": "user", "content": "唯一初始输入-PG1"}],
                    "files": dr.materials_files({"task_prompt.md": materials.task_prompt}),
                }
            else:
                inputs = None
            self.observations.append({"state": state_kind, "inputs_none": inputs is None})
            if state_kind == "complete":
                # Mirror the production adapter: a completed graph is re-read
                # for the business re-commit, never re-streamed (streaming a
                # completed thread yields zero events).
                return _fixed_result(materials)
            if self._crash:
                if state_kind == "new":
                    try:
                        for _mode, _payload in agent.stream(
                            inputs, config=session.thread_config(),
                            stream_mode=list(dr.STREAM_MODES), durability="sync",
                        ):
                            pass
                    except dr.BudgetExceededError:
                        pass  # died mid-run exactly like a crashed worker
                raise RubricGenerationFailure("SIMULATED_CRASH", "模拟 Worker 崩溃。", retryable=True)
            dr.run_streaming(agent, session, inputs=inputs, sink=sink)
            if self._crash_after_complete and state_kind != "complete":
                # Graph finished and checkpointed, but the business commit
                # never happened (worker died in the window): the next attempt
                # must re-commit from the stored result WITHOUT any model call.
                raise RubricGenerationFailure(
                    "SIMULATED_COMMIT_CRASH", "模拟业务提交前崩溃。", retryable=True
                )
            return _fixed_result(materials)
        finally:
            session.close()


@pytest.fixture()
def pg_business_env():
    import psycopg

    dsn = _test_dsn()
    try:
        with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as probe:
            with probe.cursor() as cur:
                cur.execute("SELECT current_database()")
                assert cur.fetchone()[0] == TEST_DB_NAME
    except Exception as exc:  # noqa: BLE001
        message = f"PostgreSQL 测试库 {TEST_DB_NAME} 不可达：{type(exc).__name__}: {exc}"
        if os.environ.get("RUNTIME_PG_REQUIRED") == "1":
            pytest.fail(message + "（RUNTIME_PG_REQUIRED=1：验收运行禁止跳过）")
        pytest.skip(message + "（跳过不构成持久化验收证据）")
    original = settings.checkpoint_database_url
    from pydantic import SecretStr

    settings.checkpoint_database_url = SecretStr(dsn)
    clear_business_data()
    yield dsn
    settings.checkpoint_database_url = original


def _upload(client: TestClient, case_id: str) -> str:
    helpers.register_admin(client)
    scene = helpers.create_scene(client)
    credential = helpers.create_credential(client, scene["id"])
    response = helpers.upload_batch(
        client, credential["token"], helpers.make_batch(f"cmd-{case_id}", [helpers.make_case(case_id)])
    )
    assert response.status_code == 201, response.text
    return response.json()["cases"][0]["question_id"]


def test_crash_resume_and_complete_deletion_on_real_checkpoints(pg_business_env) -> None:
    dsn = pg_business_env
    previous = get_adapters()
    crash_gen = _PgStubGenerator(dsn, crash_after=True)
    try:
        with TestClient(app) as client:
            question_id = _upload(client, "case-pg-durable")
            thread_id = f"qgen-{question_id}-r1"
            _clean_from_dsn(dsn, thread_id)

            # Attempt 1..N: real checkpoint writes, then a simulated crash on
            # every attempt until the budget is exhausted.
            set_adapters(RuntimeAdapters(rubric_generator=crash_gen))
            helpers.run_worker_until_idle()
            detail = client.get(f"/api/questions/{question_id}").json()
            assert detail["status"] == "generation_failed"
            assert crash_gen.observations[0]["state"] == "new"
            assert crash_gen.observations[0]["inputs_none"] is False
            # Retried attempts found the incomplete checkpoint and did NOT
            # re-submit the initial input.
            resumed = [o for o in crash_gen.observations[1:] if o["state"] == "incomplete"]
            assert resumed and all(o["inputs_none"] for o in resumed)

            # Retry with a healthy generator: resumes and completes.
            resume_gen = _PgStubGenerator(dsn)
            set_adapters(RuntimeAdapters(rubric_generator=resume_gen))
            retry = client.post(
                f"/api/questions/{question_id}/generation-retry",
                json={"command_id": "retry-pg", "content_revision": detail["content_revision"]},
            )
            assert retry.status_code == 200, retry.text
            helpers.run_worker_until_idle()
            detail = client.get(f"/api/questions/{question_id}").json()
            assert detail["status"] == "pending_review", detail
            assert resume_gen.observations, "resume attempt did not run"
            assert resume_gen.observations[-1]["state"] == "incomplete"
            assert resume_gen.observations[-1]["inputs_none"] is True, (
                "恢复必须续跑检查点，不得重复提交初始输入"
            )
            criteria = detail["criteria"]
            assert criteria and criteria[0]["score_anchors"]

            # Thread registry + events from BOTH attempts persisted.
            with session_scope() as session:
                from sqlalchemy import func, select

                threads = session.execute(
                    select(QuestionRunThreadRow).where(
                        QuestionRunThreadRow.question_id == question_id
                    )
                ).scalars().all()
                assert len(threads) == 1 and threads[0].thread_id == thread_id
                event_count = session.execute(
                    select(func.count()).select_from(QuestionRunEventRow).where(
                        QuestionRunEventRow.question_id == question_id
                    )
                ).scalar_one()
            assert event_count > 0

            # Checkpoint rows really exist in PostgreSQL before deletion.
            import psycopg

            with psycopg.connect(dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT count(*) FROM checkpoints WHERE thread_id = %s", (thread_id,)
                    )
                    assert cur.fetchone()[0] > 0

            # Accepted deletion drives the real cross-store cleanup.
            accepted = client.request(
                "DELETE",
                f"/api/questions/{question_id}",
                json={"command_id": "del-pg", "content_revision": detail["content_revision"]},
            )
            assert accepted.status_code == 202, accepted.text
            helpers.run_worker_until_idle()
            assert client.get(f"/api/questions/{question_id}").status_code == 404

            # Zero residue in BOTH stores.
            with psycopg.connect(dsn, autocommit=True) as conn:
                residue = dr.thread_data_residue(conn, thread_id)
            assert all(v == 0 for v in residue.values()), residue
            with session_scope() as session:
                from sqlalchemy import select

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
        set_adapters(previous)


def _clean_from_dsn(dsn: str, thread_id: str) -> None:
    import psycopg

    from pydantic import SecretStr

    class _Cfg:
        checkpoint_database_url = SecretStr(dsn)
        langgraph_aes_key = settings.langgraph_aes_key

    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            saver = dr.build_saver(conn, _Cfg())
            saver.setup()
            session = dr.CheckpointSession(conn, saver, thread_id)
            session.acquire_lock()
            try:
                dr.delete_thread_data(session)
            finally:
                session.close()
    except dr.ThreadLockBusyError:
        pass


def test_completed_graph_recommits_without_model_call(pg_business_env) -> None:
    """C-1 regression: a thread whose graph COMPLETED but whose business save
    never happened must be re-committed from the stored checkpoint result —
    streaming a completed thread is skipped entirely (no RUNTIME_NO_EVENTS,
    no model call), and the retry lands the criteria."""
    dsn = pg_business_env
    previous = get_adapters()
    question_id = None
    try:
        with TestClient(app) as client:
            question_id = _upload(client, "case-pg-recommit")
            thread_id = f"qgen-{question_id}-r1"
            _clean_from_dsn(dsn, thread_id)

            # Attempt 1 completes the graph then "crashes" before the business
            # commit; attempt 2 finds state=complete and re-commits from the
            # stored result without streaming or any model call.
            crash_gen = _PgStubGenerator(dsn, crash_after_complete=True)
            set_adapters(RuntimeAdapters(rubric_generator=crash_gen))
            helpers.run_worker_until_idle()
            detail = client.get(f"/api/questions/{question_id}").json()
            assert detail["status"] == "pending_review", detail
            assert detail["criteria"], "补提交必须落库完整候选"
            states = [o["state"] for o in crash_gen.observations]
            assert states[0] == "new"
            assert states[-1] == "complete"
            assert crash_gen.observations[-1]["inputs_none"] is True
    finally:
        set_adapters(previous)
        if question_id:
            _clean_from_dsn(dsn, f"qgen-{question_id}-r1")
