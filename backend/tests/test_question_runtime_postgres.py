"""Business-chain durability tests on the task-exclusive PostgreSQL database.

Proves, through the REAL worker handler and business API (not just runtime
primitives): thread registration, checkpoint-backed resume across a simulated
worker crash without duplicated initial input, persisted public events across
attempts, and complete cross-store deletion (business rows + checkpoint rows)
with zero residue.

Gated like the C2 primitive tests: skips loudly without PostgreSQL and fails
under RUNTIME_PG_REQUIRED=1. Never touches blue_benchmark / blue_benchmark_checkpoint.
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
    helpers.login_admin(client)
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


def _materials_for(thread_case: str):
    from app.lib.ai_runtime.adapters import RubricGenerationInput

    return RubricGenerationInput(
        task_prompt=f"{thread_case} 的任务材料。",
        reference_examples=[],
        bad_cases=[],
        reference_answer=f"{thread_case} 的老师认可标准答案全文。",
        memory_materials=[],
    )


def test_real_adapter_recommits_completed_thread_without_streaming(pg_business_env, monkeypatch) -> None:
    """MAJ-1 regression: locks the PRODUCTION adapter's complete-skip branch.

    If the fix is reverted (completed thread still streamed), run_streaming
    yields zero events and raises RUNTIME_NO_EVENTS — this test goes red.
    """
    from app.lib.ai_runtime import deep_runtime as dr
    from app.lib.ai_runtime.adapters import DeepAgentRubricGenerator, RunContext
    from pydantic import SecretStr

    dsn = pg_business_env
    thread_id = "qgen-direct-recommit-r1"
    _clean_from_dsn(dsn, thread_id)

    class _Cfg:
        checkpoint_database_url = SecretStr(dsn)
        from app.lib.settings import settings as _s
        langgraph_aes_key = _s.langgraph_aes_key

    materials = _materials_for("direct-recommit")
    context = RunContext(
        thread_id=thread_id,
        operation_id="op-direct",
        attempt_number=1,
        question_id="q-direct",
        materials_revision=1,
        materials_fingerprint="f" * 64,
    )

    # Phase 1: bring the thread to COMPLETE with the stub generator.
    stub = _PgStubGenerator(dsn)
    from app.lib.ai_runtime.deep_runtime import ListSink

    stub.generate(materials, context=context, sink=ListSink())

    # Phase 2: the REAL production adapter, with an empty model script (any
    # model call or streaming attempt would blow up) and the structured read
    # stubbed to return the stored-shaped result.
    def _fake_structured(agent, session):
        return _fixed_result(materials)

    monkeypatch.setattr(dr, "final_structured_response", _fake_structured)

    def _session_factory(ctx):
        session = dr.open_session(ctx.thread_id, _Cfg())
        return session

    adapter = DeepAgentRubricGenerator(
        model=ScriptedModel(messages=iter([])),
        identity=IDENTITY,
        session_factory=_session_factory,
    )
    sink = ListSink()
    result = adapter.generate(materials, context=context, sink=sink)
    assert result.criteria
    # The completion path must have been taken without streaming: no
    # message_delta events exist and the resume marker shows state=complete.
    assert not [e for e in sink.events if e.kind == "message_delta"]
    assert any(
        e.kind == "run_resumed" and e.stage == "thread_state_complete" for e in sink.events
    )
    _clean_from_dsn(dsn, thread_id)


def test_runtime_fingerprint_mismatch_purges_and_recovers(pg_business_env) -> None:
    """MAJ-2 regression: after a runtime identity change, the incompatible
    thread is purged and the retry starts a FRESH run on the same revision —
    teacher retries recover instead of dead-ending."""
    from sqlalchemy import select, update as sa_update

    from app.features.question_library import run_streams
    from app.lib.database.models import QuestionRunThreadRow

    dsn = pg_business_env
    previous = get_adapters()
    question_id = None
    try:
        with TestClient(app) as client:
            question_id = _upload(client, "case-pg-fingerprint")
            thread_id = f"qgen-{question_id}-r1"
            _clean_from_dsn(dsn, thread_id)

            # Phase 1: a real checkpointed run that crashes (retryable).
            crash_gen = _PgStubGenerator(dsn, crash_after=True)
            set_adapters(RuntimeAdapters(rubric_generator=crash_gen))
            helpers.run_worker_until_idle()
            detail = client.get(f"/api/questions/{question_id}").json()
            assert detail["status"] == "generation_failed"

            # The deployment's runtime identity changes (model/SDK upgrade).
            with session_scope() as session:
                session.execute(
                    sa_update(QuestionRunThreadRow)
                    .where(QuestionRunThreadRow.thread_id == thread_id)
                    .values(runtime_fingerprint="stale-runtime-id")
                )

            # Retry under a healthy generator: the stale thread must be purged
            # and the run restarts fresh (state=new), then completes.
            healthy = _PgStubGenerator(dsn)
            set_adapters(RuntimeAdapters(rubric_generator=healthy))
            retry = client.post(
                f"/api/questions/{question_id}/generation-retry",
                json={"command_id": "retry-fp", "content_revision": detail["content_revision"]},
            )
            assert retry.status_code == 200, retry.text
            helpers.run_worker_until_idle()
            detail = client.get(f"/api/questions/{question_id}").json()
            assert detail["status"] == "pending_review", detail.get("last_error")
            assert healthy.observations, "recovery run did not execute"
            assert healthy.observations[-1]["state"] == "new", (
                "清除不兼容线程后必须全新开跑，而不是续跑旧检查点"
            )
            with session_scope() as session:
                row = session.execute(
                    select(QuestionRunThreadRow).where(
                        QuestionRunThreadRow.thread_id == thread_id
                    )
                ).scalar_one()
            assert row.runtime_fingerprint != "stale-runtime-id"
    finally:
        set_adapters(previous)
        if question_id:
            _clean_from_dsn(dsn, f"qgen-{question_id}-r1")


def test_real_adapter_resume_never_duplicates_initial_input(pg_business_env, monkeypatch) -> None:
    """MAJ-1 (C4 round): DIRECT proof on the production adapter that an
    incomplete thread resumes without re-appending the initial input — the
    checkpoint ends with exactly one HumanMessage."""
    from langchain_core.messages import AIMessage, HumanMessage

    from app.lib.ai_runtime import deep_runtime as dr
    from app.lib.ai_runtime.adapters import (
        DeepAgentRubricGenerator,
        RubricGenerationInput,
        RunContext,
    )
    from app.lib.ai_runtime.deep_runtime import ListSink
    from pydantic import SecretStr
    from tests.test_question_runtime_postgres import _clean_from_dsn, _fixed_result

    dsn = pg_business_env
    thread_id = "qgen-direct-resume-r1"
    _clean_from_dsn(dsn, thread_id)

    class _Cfg:
        checkpoint_database_url = SecretStr(dsn)
        from app.lib.settings import settings as _s
        langgraph_aes_key = _s.langgraph_aes_key

    materials = RubricGenerationInput(
        task_prompt="直接恢复测试任务。", reference_answer="直接恢复测试的标准答案。"
    )
    context = RunContext(
        thread_id=thread_id, operation_id="op-direct-resume", attempt_number=1,
        question_id="q-direct-resume", materials_revision=1,
        materials_fingerprint="f" * 64,
    )

    def _session_factory(ctx):
        return dr.open_session(ctx.thread_id, _Cfg())

    # Phase 1: real adapter, budget capped at one model call — the scripted
    # model issues a tool call, the tool round persists, then the budget
    # kills the second model call: a genuinely incomplete thread.
    tool_call = AIMessage(
        content="",
        tool_calls=[{"name": "write_file",
                     "args": {"file_path": "/workspace/note.md", "content": "中途笔记"},
                     "id": "w1", "type": "tool_call"}],
    )
    gen1 = DeepAgentRubricGenerator(
        model=ScriptedModel(messages=iter([tool_call, AIMessage(content="不会到达")])),
        identity=IDENTITY,
        session_factory=_session_factory,
        budget=dr.RuntimeBudget(max_model_calls=1),
    )
    from app.lib.ai_runtime.adapters import RubricGenerationFailure

    with pytest.raises(RubricGenerationFailure) as exc_info:
        gen1.generate(materials, context=context, sink=ListSink())
    assert exc_info.value.code == "RUNTIME_BUDGET_EXCEEDED"

    # Phase 2: real adapter resumes. The stored structured read is stubbed
    # (ScriptedModel cannot produce response_format output), but the RESUME
    # decision, input handling and message history are the real adapter's.
    monkeypatch.setattr(dr, "final_structured_response",
                        lambda agent, session: _fixed_result(materials))
    gen2 = DeepAgentRubricGenerator(
        model=ScriptedModel(messages=iter([AIMessage(content="恢复后完成。")])),
        identity=IDENTITY,
        session_factory=_session_factory,
    )
    sink2 = ListSink()
    result = gen2.generate(materials, context=context, sink=sink2)
    assert result.criteria
    assert any(
        e.kind == "run_resumed" and e.stage == "thread_state_incomplete" for e in sink2.events
    )
    # DIRECT evidence: the checkpointed conversation holds exactly ONE
    # HumanMessage — the resume did not re-append the initial input.
    session = _session_factory(context)
    try:
        agent = dr.build_restricted_agent(
            ScriptedModel(messages=iter([])), IDENTITY,
            system_prompt="x", budget=dr.RuntimeBudget(),
            counters=dr.BudgetCounters(), sink=ListSink(),
            checkpointer=session.saver,
        )
        state = agent.get_state(session.thread_config())
        humans = [m for m in state.values["messages"] if isinstance(m, HumanMessage)]
        assert len(humans) == 1, f"恢复后初始输入重复：{len(humans)} 条 HumanMessage"
    finally:
        session.close()
    _clean_from_dsn(dsn, thread_id)
