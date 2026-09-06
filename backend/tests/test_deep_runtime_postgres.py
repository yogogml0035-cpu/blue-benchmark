"""PostgreSQL durability tests for the deep-agent runtime primitives.

These tests run against a TASK-EXCLUSIVE database on the same Docker
PostgreSQL instance (``skill_eval_c2_runtime_test`` derived from the
configured checkpoint DSN). They never touch the project's ``skill_eval`` or
``skill_eval_checkpoint`` databases.

If no PostgreSQL is reachable the module skips loudly with an explicit reason
— a skip here is never real persistence evidence; the C2 acceptance run must
execute these with Docker up.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest

from app.lib.ai_runtime import deep_runtime as dr
from app.lib.ai_runtime.model import RuntimeModelIdentity

pytest.importorskip("psycopg")

from tests.test_deep_runtime import IDENTITY, ScriptedModel, scripted_agent  # noqa: E402

TEST_DB_NAME = "skill_eval_c2_runtime_test"


def _test_dsn() -> str:
    override = os.environ.get("RUNTIME_CHECKPOINT_TEST_DSN")
    if override:
        return override
    base = os.environ.get("CHECKPOINT_DATABASE_URL", "")
    if not base:
        # Fall back to the .env loaded by settings (same variable).
        from app.lib.settings import settings

        base = settings.checkpoint_database_url.get_secret_value()
    if not base:
        message = (
            "CHECKPOINT_DATABASE_URL 未配置：PostgreSQL 持久化测试无法执行"
            "（验收运行必须在 Docker PostgreSQL 可用时执行）"
        )
        if os.environ.get("RUNTIME_PG_REQUIRED") == "1":
            pytest.fail(message)
        pytest.skip(message)
    parts = urlsplit(base)
    scheme = parts.scheme.replace("+psycopg", "")
    return urlunsplit((scheme, parts.netloc, f"/{TEST_DB_NAME}", "", ""))


class _Cfg:
    def __init__(self, dsn: str) -> None:
        from pydantic import SecretStr

        self.checkpoint_database_url = SecretStr(dsn)
        self.langgraph_aes_key = SecretStr("c2-test-key-32-bytes-long-aaaaaa")


@pytest.fixture(scope="module")
def pg_env() -> Any:
    """Use the task-exclusive test database; never touch project databases.

    Preparation (once per machine, superuser role)::

        docker exec skill-eval-platform-postgres psql -U skill_eval -d postgres \
          -c 'CREATE DATABASE skill_eval_c2_runtime_test OWNER skill_eval_checkpoint'
    """
    import psycopg

    dsn = _test_dsn()
    cfg = _Cfg(dsn)
    try:
        with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as probe:
            with probe.cursor() as cur:
                cur.execute("SELECT current_database()")
                assert cur.fetchone()[0] == TEST_DB_NAME
    except Exception as exc:  # noqa: BLE001
        message = (
            f"PostgreSQL 测试库 {TEST_DB_NAME} 不可达。准备命令见 fixture docstring。"
            f"原因：{type(exc).__name__}: {exc}"
        )
        if os.environ.get("RUNTIME_PG_REQUIRED") == "1":
            pytest.fail(f"{message}（RUNTIME_PG_REQUIRED=1：验收运行禁止跳过）")
        pytest.skip(f"{message}（跳过不构成持久化验收证据）")
    yield cfg
    # Leave the database in place (task-exclusive); per-test cleanup happens
    # via delete_thread_data inside each test.


def _open(cfg: Any, thread_id: str) -> dr.CheckpointSession:
    import psycopg

    conn = psycopg.connect(dr.checkpoint_dsn(cfg), autocommit=True)
    try:
        saver = dr.build_saver(conn, cfg)
        saver.setup()
        session = dr.CheckpointSession(conn, saver, thread_id)
        session.acquire_lock()
        return session
    except BaseException:
        conn.close()
        raise


def _clean(cfg: Any, thread_id: str) -> None:
    """Remove any residue of a previous failed run before a test starts."""
    session = _open(cfg, thread_id)
    try:
        dr.delete_thread_data(session)
    finally:
        session.close()


def _agent_with(saver: Any, replies: list[Any], **kwargs: Any):
    model = ScriptedModel(messages=iter(replies))
    sink = dr.ListSink()
    agent = dr.build_restricted_agent(
        model,
        IDENTITY,
        system_prompt="PG 测试系统提示",
        budget=kwargs.pop("budget", dr.RuntimeBudget()),
        counters=dr.BudgetCounters(),
        sink=sink,
        checkpointer=saver,
        **kwargs,
    )
    return agent, sink


def _write_notes_call(path: str, content: str, call_id: str):
    from langchain_core.messages import AIMessage

    return AIMessage(
        content="",
        tool_calls=[{
            "name": "write_file",
            "args": {"file_path": path, "content": content},
            "id": call_id,
            "type": "tool_call",
        }],
    )


def _final(text: str):
    from langchain_core.messages import AIMessage

    return AIMessage(content=text)


# ---------------------------------------------------------------------------
# Durability across "restarts" (fresh connection + fresh saver + fresh agent)
# ---------------------------------------------------------------------------

def test_state_survives_restart_without_duplicating_input(pg_env):
    from langchain_core.messages import HumanMessage

    thread = "pg-restart-1"
    _clean(pg_env, thread)
    marker = "唯一工作文件标记-ZQX7"
    session = _open(pg_env, thread)
    try:
        agent, sink = _agent_with(
            session.saver,
            [_write_notes_call("/workspace/notes.md", marker, "c1"), _final("完成")],
        )
        inputs = {
            "messages": [HumanMessage(content="初始输入-UYT5")],
            "files": dr.materials_files({"task.md": "材料-ABC1"}),
        }
        values = dr.run_streaming(agent, session, inputs=inputs, sink=sink)
        assert values["files"]["/workspace/notes.md"]["content"] == marker
        assert any(e.kind == "run_completed" for e in sink.events)

        # A fresh initial input against the existing checkpoint is refused —
        # restore must never re-append the input.
        agent_dup, sink_dup = _agent_with(session.saver, [_final("不应执行")])
        with pytest.raises(dr.DeepRuntimeError) as exc_info:
            dr.run_streaming(agent_dup, session, inputs=inputs, sink=sink_dup)
        assert exc_info.value.code == "THREAD_INPUT_CONFLICT"
    finally:
        session.close()

    # "Restart": brand-new connection, saver, agent and counters. The graph
    # completed, so the caller reads persisted state instead of streaming.
    session2 = _open(pg_env, thread)
    try:
        agent2, _ = _agent_with(session2.saver, [])
        assert dr.classify_thread_state(agent2, session2.thread_config()) == "complete"
        state = agent2.get_state(session2.thread_config())
        values2 = dict(state.values)
        humans = [m for m in values2["messages"] if isinstance(m, HumanMessage)]
        assert len(humans) == 1, "恢复不得重复追加初始输入"
        assert values2["files"]["/workspace/notes.md"]["content"] == marker
        assert values2["files"]["/materials/task.md"]["content"] == "材料-ABC1"
        assert dr.final_files(agent2, session2)["/workspace/notes.md"]["content"] == marker
    finally:
        dr.delete_thread_data(session2)
        session2.close()


def test_checkpoint_bytes_are_encrypted_at_rest(pg_env):
    thread = "pg-encrypt-1"
    _clean(pg_env, thread)
    plaintext_marker = "明文标记不可入库-QQ81"
    session = _open(pg_env, thread)
    try:
        agent, sink = _agent_with(
            session.saver,
            [_write_notes_call("/workspace/secret-note.md", plaintext_marker, "c1"),
             _final("完成")],
        )
        dr.run_streaming(
            agent,
            session,
            inputs={"messages": [{"role": "user", "content": "写入工作文件"}],
                    "files": dr.materials_files({"task.md": "材料"})},
            sink=sink,
        )
        # Raw blob scan: the marker must not appear in any stored byte.
        found = 0
        with session.conn.cursor() as cur:
            cur.execute(
                "SELECT blob FROM checkpoint_blobs WHERE thread_id = %s", (thread,)
            )
            for (blob,) in cur.fetchall():
                raw = blob if isinstance(blob, (bytes, bytearray, memoryview)) else bytes(
                    blob or b""
                )
                if plaintext_marker.encode("utf-8") in bytes(raw):
                    found += 1
        assert found == 0, "检查点以明文存储了工作文件内容"
        # And the encrypted payload decrypts through the saver.
        files = dr.final_files(agent, session)
        assert files["/workspace/secret-note.md"]["content"] == plaintext_marker
        # Stored type tag records the cipher.
        with session.conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT type FROM checkpoint_blobs WHERE thread_id = %s",
                (thread,),
            )
            types = [row[0] for row in cur.fetchall()]
        assert any("+aes" in t for t in types), f"未见加密类型标记：{types}"
    finally:
        dr.delete_thread_data(session)
        session.close()


# ---------------------------------------------------------------------------
# Single-writer advisory lock
# ---------------------------------------------------------------------------

def test_same_thread_second_writer_is_refused(pg_env):
    thread = "pg-lock-1"
    _clean(pg_env, thread)
    _clean(pg_env, "pg-lock-other")
    session = _open(pg_env, thread)
    try:
        with pytest.raises(dr.ThreadLockBusyError):
            _open(pg_env, thread)
        # A DIFFERENT thread on a second connection is unaffected.
        other = _open(pg_env, "pg-lock-other")
        other.close()
    finally:
        session.close()
    # After release, the lock is acquirable again.
    session2 = _open(pg_env, thread)
    session2.close()


def test_lock_dies_with_connection_so_stale_writer_cannot_continue(pg_env):
    thread = "pg-lock-crash-1"
    _clean(pg_env, thread)
    session = _open(pg_env, thread)
    # Simulate a crashed worker: close the raw connection without unlocking.
    session.conn.close()
    session._closed = True
    # Session-level advisory locks are released by PostgreSQL on disconnect.
    session2 = _open(pg_env, thread)
    assert session2.lock_held
    session2.close()


# ---------------------------------------------------------------------------
# Cleanup primitives (model-free)
# ---------------------------------------------------------------------------

def test_delete_thread_covers_all_row_groups_and_spares_others(pg_env):
    thread_a, thread_b = "pg-del-a", "pg-del-b"
    _clean(pg_env, thread_a)
    _clean(pg_env, thread_b)
    session_a = _open(pg_env, thread_a)
    session_b = _open(pg_env, thread_b)
    try:
        for session, tid in ((session_a, thread_a), (session_b, thread_b)):
            agent, sink = _agent_with(
                session.saver,
                [_write_notes_call("/workspace/n.md", f"note-{tid}", "c1"), _final("完成")],
            )
            dr.run_streaming(
                agent,
                session,
                inputs={"messages": [{"role": "user", "content": f"任务-{tid}"}],
                        "files": dr.materials_files({"task.md": "材料"})},
                sink=sink,
            )
        before = dr.thread_data_residue(session_a.conn, thread_a)
        assert all(v > 0 for v in before.values()), f"运行后应有检查点数据：{before}"
        assert all(v > 0 for v in dr.thread_data_residue(session_b.conn, thread_b).values())

        dr.delete_thread_data(session_a)
        assert all(v == 0 for v in dr.thread_data_residue(session_a.conn, thread_a).values())
        # Sibling thread untouched.
        assert all(v > 0 for v in dr.thread_data_residue(session_b.conn, thread_b).values())
        # State gone through a fresh agent view too.
        agent_b, _ = _agent_with(session_b.saver, [])
        assert dr.classify_thread_state(agent_b, {"configurable": {"thread_id": thread_a}}) == "new"
    finally:
        dr.delete_thread_data(session_b)
        session_a.close()
        session_b.close()


def test_cleanup_never_needs_a_model_provider(pg_env, monkeypatch):
    def _explode(*args: Any, **kwargs: Any):
        raise AssertionError("cleanup must not build a model")

    monkeypatch.setattr("app.lib.ai_runtime.model.build_runtime_model", _explode)
    thread = "pg-del-nomodel"
    _clean(pg_env, thread)
    session = _open(pg_env, thread)
    try:
        agent, sink = _agent_with(
            session.saver,
            [_write_notes_call("/workspace/n.md", "note", "c1"), _final("完成")],
        )
        dr.run_streaming(
            agent,
            session,
            inputs={"messages": [{"role": "user", "content": "任务"}],
                    "files": dr.materials_files({"task.md": "材料"})},
            sink=sink,
        )
        residue = dr.delete_thread_data(session)
        assert all(v == 0 for v in residue.values())
    finally:
        session.close()


def test_cleanup_is_idempotent(pg_env):
    thread = "pg-del-twice"
    _clean(pg_env, thread)
    session = _open(pg_env, thread)
    try:
        dr.delete_thread_data(session)
        dr.delete_thread_data(session)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Interrupt / resume protocol (M1 groundwork, no business entrypoint)
# ---------------------------------------------------------------------------

def test_interrupt_parks_then_resumes_without_rerunning_input(pg_env):
    from langchain_core.messages import AIMessage, HumanMessage
    from langchain_core.tools import tool
    from langgraph.types import Command, interrupt

    @tool
    def ask_teacher(question: str) -> str:
        """向老师提问并等待回复（协议验证工具，仅测试使用）。"""
        return interrupt({"question": question})

    thread = "pg-interrupt-1"
    _clean(pg_env, thread)
    session = _open(pg_env, thread)
    try:
        # Script: call ask_teacher, then finish after the resume.
        agent, sink = _agent_with(
            session.saver,
            [
                AIMessage(
                    content="",
                    tool_calls=[{"name": "ask_teacher", "args": {"question": "通过分是多少？"},
                                 "id": "q1", "type": "tool_call"}],
                ),
                AIMessage(content="收到回复，完成。"),
            ],
            tools=[ask_teacher],
        )
        dr.run_streaming(
            agent,
            session,
            inputs={"messages": [HumanMessage(content="唯一初始输入-KK31")],
                    "files": dr.materials_files({"task.md": "材料"})},
            sink=sink,
        )
        interrupted, payloads = dr.inspect_interrupt(agent, session)
        assert interrupted and payloads[0]["question"] == "通过分是多少？"
        assert dr.classify_thread_state(agent, session.thread_config()) == "incomplete"
        assert any(e.kind == "interrupted" for e in sink.events)
        assert not any(e.kind == "run_completed" for e in sink.events)
    finally:
        session.close()

    # "Restart" and resume with the answer.
    session2 = _open(pg_env, thread)
    try:
        agent2, sink2 = _agent_with(
            session2.saver, [_final("恢复后收尾。")], tools=[ask_teacher]
        )
        values = dr.run_streaming(
            agent2, session2, inputs=Command(resume="7 分"), sink=sink2
        )
        humans = [m for m in values["messages"] if isinstance(m, HumanMessage)]
        assert len(humans) == 1, "resume 不得重复初始输入"
        tool_msgs = [m for m in values["messages"] if m.type == "tool"]
        assert any("7 分" in str(m.content) for m in tool_msgs)
        assert dr.classify_thread_state(agent2, session2.thread_config()) == "complete"
    finally:
        dr.delete_thread_data(session2)
        session2.close()


# ---------------------------------------------------------------------------
# Thread isolation
# ---------------------------------------------------------------------------

def test_threads_are_isolated_in_one_database(pg_env):
    thread_a, thread_b = "pg-iso-a", "pg-iso-b"
    _clean(pg_env, thread_a)
    _clean(pg_env, thread_b)
    session_a = _open(pg_env, thread_a)
    session_b = _open(pg_env, thread_b)
    try:
        agent_a, sink_a = _agent_with(
            session_a.saver,
            [_write_notes_call("/workspace/a.md", "A私有工作文件", "c1"), _final("A完成")],
        )
        dr.run_streaming(
            agent_a,
            session_a,
            inputs={"messages": [{"role": "user", "content": "A 题输入"}],
                    "files": dr.materials_files({"task.md": "A 题材料-XA91"})},
            sink=sink_a,
        )
        agent_b, sink_b = _agent_with(session_b.saver, [_final("B完成")])
        values_b = dr.run_streaming(
            agent_b,
            session_b,
            inputs={"messages": [{"role": "user", "content": "B 题输入"}],
                    "files": dr.materials_files({"task.md": "B 题材料-XB92"})},
            sink=sink_b,
        )
        files_b = values_b.get("files") or {}
        assert "/workspace/a.md" not in files_b
        assert files_b["/materials/task.md"]["content"] == "B 题材料-XB92"
        texts_b = " ".join(str(m.content) for m in values_b["messages"])
        assert "A 题材料-XA91" not in texts_b and "A私有工作文件" not in texts_b
        # A unchanged after B ran.
        values_a = dr.final_files(agent_a, session_a)
        assert values_a["/materials/task.md"]["content"] == "A 题材料-XA91"
    finally:
        dr.delete_thread_data(session_a)
        dr.delete_thread_data(session_b)
        session_a.close()
        session_b.close()


def test_budget_abort_leaves_resumable_incomplete_thread(pg_env):
    """预算在运行中超限：线程留下 incomplete 检查点，盲目续跑再次撞预算（fail-closed）。"""
    thread = "pg-budget-abort"
    _clean(pg_env, thread)
    session = _open(pg_env, thread)
    try:
        script = [
            _write_notes_call("/workspace/a.md", "第一轮工作", "c1"),
            _write_notes_call("/workspace/b.md", "第二轮工作", "c2"),
            _final("本不应到达"),
        ]
        counters = dr.BudgetCounters()
        model = ScriptedModel(messages=iter(script))
        sink = dr.ListSink()
        agent = dr.build_restricted_agent(
            model, IDENTITY,
            system_prompt="预算测试",
            budget=dr.RuntimeBudget(max_model_calls=2),
            counters=counters,
            sink=sink,
            checkpointer=session.saver,
        )
        with pytest.raises(dr.BudgetExceededError):
            dr.run_streaming(
                agent, session,
                inputs={"messages": [{"role": "user", "content": "唯一输入"}],
                        "files": dr.materials_files({"task.md": "材料"})},
                sink=sink,
            )
        assert dr.classify_thread_state(agent, session.thread_config()) == "incomplete"
        # Blind resume hits the same ceiling again instead of silently
        # continuing to spend.
        with pytest.raises(dr.BudgetExceededError):
            dr.run_streaming(agent, session, inputs=None, sink=sink)
    finally:
        dr.delete_thread_data(session)
        session.close()


def test_encrypted_at_rest_full_column_scan(pg_env):
    """消息与工作文件的双标记在三张表所有字节列中都不出现（固化审查实证）。"""
    thread = "pg-encrypt-full"
    _clean(pg_env, thread)
    msg_marker = "消息明文标记-ZZ41"
    file_marker = "文件明文标记-ZZ42"
    session = _open(pg_env, thread)
    try:
        agent, sink = _agent_with(
            session.saver,
            [_write_notes_call("/workspace/note.md", file_marker, "c1"), _final("完成")],
        )
        dr.run_streaming(
            agent, session,
            inputs={"messages": [{"role": "user", "content": msg_marker}],
                    "files": dr.materials_files({"task.md": "材料"})},
            sink=sink,
        )
        scans = {
            "checkpoints": ["checkpoint::text", "metadata::text"],
            "checkpoint_writes": ["blob::text"],
            "checkpoint_blobs": ["blob::text"],
        }
        for table, columns in scans.items():
            for column in columns:
                with session.conn.cursor() as cur:
                    cur.execute(
                        f"SELECT count(*) FROM {table} "  # noqa: S608 - fixed test-local names
                        f"WHERE thread_id = %s AND {column} LIKE %s",
                        (thread, f"%{msg_marker}%"),
                    )
                    assert cur.fetchone()[0] == 0, f"{table}.{column} 泄露消息明文"
                    cur.execute(
                        f"SELECT count(*) FROM {table} "  # noqa: S608
                        f"WHERE thread_id = %s AND {column} LIKE %s",
                        (thread, f"%{file_marker}%"),
                    )
                    assert cur.fetchone()[0] == 0, f"{table}.{column} 泄露文件明文"
    finally:
        dr.delete_thread_data(session)
        session.close()
