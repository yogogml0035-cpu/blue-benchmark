"""Contract tests for the deep-agent runtime primitives (stub level).

These tests use a scripted fake chat model and InMemorySaver to verify the
RESTRICTION and NORMALIZATION contracts deterministically. PostgreSQL
durability, single-writer locks and real-provider behavior are covered by
test_deep_runtime_postgres.py and the probe script — nothing here claims to
prove persistence.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.lib.ai_runtime import deep_runtime as dr
from app.lib.ai_runtime.model import RuntimeModelIdentity

IDENTITY = RuntimeModelIdentity(provider="openai", model="scripted-test-model", base_url=None)


BOUND_TOOL_LOG: list[list[str]] = []


class ScriptedModel(GenericFakeChatModel):
    """Fake model that accepts bind_tools and replays scripted AIMessages.

    Records the tool names actually bound for each model call into
    ``BOUND_TOOL_LOG`` — the innermost observation point, after all middleware
    (including the harness tool-exclusion layer) filtered the request.

    ``_stream`` yields each scripted message as a single chunk so streaming
    runs work with empty-content tool-call messages (the stock fake raises
    "No generations found in stream" for those).
    """

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedModel":
        BOUND_TOOL_LOG.append([getattr(t, "name", str(t)) for t in tools])
        return self

    def _stream(self, messages: Any, stop: Any = None, run_manager: Any = None,
                **kwargs: Any) -> Any:
        from langchain_core.messages import AIMessageChunk
        from langchain_core.outputs import ChatGenerationChunk

        try:
            msg = next(self.messages)
        except StopIteration:
            return
        chunk = AIMessageChunk(
            content=msg.content,
            tool_calls=list(getattr(msg, "tool_calls", None) or []),
            id=getattr(msg, "id", None),
        )
        yield ChatGenerationChunk(message=chunk)


def scripted_agent(replies: list[AIMessage], **kwargs: Any):
    model = ScriptedModel(messages=iter(replies))
    sink = dr.ListSink()
    budget = kwargs.pop("budget", dr.RuntimeBudget())
    agent = dr.build_restricted_agent(
        model,
        IDENTITY,
        system_prompt="测试系统提示",
        budget=budget,
        counters=dr.BudgetCounters(),
        sink=sink,
        checkpointer=InMemorySaver(),
        **kwargs,
    )
    return agent, sink


# ---------------------------------------------------------------------------
# Version locks
# ---------------------------------------------------------------------------

def test_locked_sdk_versions_match_verified():
    import importlib.metadata as md

    import deepagents

    assert getattr(deepagents, "__version__", None) == dr.VERIFIED_DEEPAGENTS_VERSION
    assert md.version("langgraph-checkpoint-postgres") == dr.VERIFIED_CHECKPOINT_POSTGRES_VERSION


# ---------------------------------------------------------------------------
# Restricted construction
# ---------------------------------------------------------------------------

def test_default_delegation_and_shell_are_not_exposed():
    BOUND_TOOL_LOG.clear()
    agent, _ = scripted_agent([AIMessage(content="ok")])
    agent.invoke(
        {"messages": [{"role": "user", "content": "hi"}]},
        config={"configurable": {"thread_id": "t-exposure"}},
    )
    names = dr.bound_tool_names(agent)
    assert "task" not in names        # no subagent delegation at all
    # The executor keeps `execute` registered (rejection happens at the call
    # boundary, proven in the next test), but the model must never see it.
    assert BOUND_TOOL_LOG, "model call did not bind tools"
    bound = set(BOUND_TOOL_LOG[0])
    assert "execute" not in bound and "task" not in bound
    assert "read_file" in bound and "ls" in bound


def test_excluded_tools_rejected_at_call_boundary_even_if_emitted():
    # A model that hallucinates an excluded tool call must get an error
    # ToolMessage, never an execution.
    call = AIMessage(
        content="",
        tool_calls=[{"name": "execute", "args": {"command": "rm -rf /"}, "id": "c1",
                     "type": "tool_call"}],
    )
    agent, sink = scripted_agent([call, AIMessage(content="done")])
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "hi"}]},
        config={"configurable": {"thread_id": "t-exclude"}},
    )
    tool_messages = [m for m in result["messages"] if m.type == "tool"]
    assert tool_messages, "excluded tool call must still produce a ToolMessage"
    assert tool_messages[0].status == "error"
    assert "not available" in str(tool_messages[0].content)


def test_materials_are_read_only():
    write_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "write_file",
            "args": {"file_path": "/materials/task.md", "content": "篡改"},
            "id": "w1", "type": "tool_call",
        }],
    )
    agent, sink = scripted_agent([write_call, AIMessage(content="done")])
    files = dr.materials_files({"task.md": "原始任务材料"})
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "hi"}], "files": files},
        config={"configurable": {"thread_id": "t-readonly"}},
    )
    # Materials unchanged.
    assert result["files"]["/materials/task.md"]["content"] == "原始任务材料"
    tool_messages = [m for m in result["messages"] if m.type == "tool"]
    assert tool_messages and tool_messages[0].status == "error"
    # The failed tool boundary was observable publicly without payload leaks.
    kinds = [e.kind for e in sink.events]
    assert "tool_started" in kinds and "tool_failed" in kinds
    for event in sink.events:
        assert "篡改" not in (event.text or "") + (event.detail or "")


def test_workspace_writes_allowed_and_persist_in_state():
    write_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "write_file",
            "args": {"file_path": "/workspace/notes.md", "content": "工作笔记"},
            "id": "w2", "type": "tool_call",
        }],
    )
    agent, _ = scripted_agent([write_call, AIMessage(content="done")])
    files = dr.materials_files({"task.md": "材料"})
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "hi"}], "files": files},
        config={"configurable": {"thread_id": "t-workspace"}},
    )
    assert result["files"]["/workspace/notes.md"]["content"] == "工作笔记"


def test_materials_files_validation():
    seeded = dr.materials_files({"a.md": "x"})
    assert list(seeded) == ["/materials/a.md"] and seeded["/materials/a.md"]["content"] == "x"
    with pytest.raises(dr.DeepRuntimeError, match="非法材料路径"):
        dr.materials_files({"../escape.md": "x"})
    with pytest.raises(dr.DeepRuntimeError, match="非法材料路径"):
        dr.materials_files({"\\windows\\path.md": "x"})
    with pytest.raises(dr.DeepRuntimeError, match="正文不能为空"):
        dr.materials_files({"a.md": "   "})
    with pytest.raises(dr.DeepRuntimeError, match="材料为空"):
        dr.materials_files({})


# ---------------------------------------------------------------------------
# Event normalization
# ---------------------------------------------------------------------------

class _Chunk:
    def __init__(self, content: Any, additional_kwargs: dict | None = None) -> None:
        self.content = content
        self.additional_kwargs = additional_kwargs or {}


def test_normalize_message_delta_and_private_filtering():
    events = dr.normalize_stream_chunk("messages", (_Chunk("公开文本"), {}))
    assert events == [dr.PublicEvent(kind="message_delta", text="公开文本")]

    # Reasoning-only chunks (block form and relay additional_kwargs form) drop.
    assert dr.normalize_stream_chunk(
        "messages", (_Chunk([{"type": "thinking", "thinking": "私有"}]), {})
    ) == []
    assert dr.normalize_stream_chunk(
        "messages", (_Chunk("", {"reasoning_content": "私有"}), {})
    ) == []
    # Mixed chunk keeps only the public text.
    mixed = _Chunk([{"type": "thinking", "thinking": "私有"}, {"type": "text", "text": "公开"}])
    events = dr.normalize_stream_chunk("messages", (mixed, {}))
    assert events == [dr.PublicEvent(kind="message_delta", text="公开")]


def test_normalize_updates_and_custom():
    events = dr.normalize_stream_chunk("updates", {"model": {"messages": ["x" * 5000]}})
    assert events == [dr.PublicEvent(kind="stage", stage="model")]
    events = dr.normalize_stream_chunk("custom", {"stage": "材料核查", "text": "已读取 3 条反馈"})
    assert events == [dr.PublicEvent(kind="stage", stage="材料核查", text="已读取 3 条反馈")]
    assert dr.normalize_stream_chunk("custom", "开始") == [
        dr.PublicEvent(kind="stage", stage="custom", text="开始")
    ]
    assert dr.normalize_stream_chunk("values", {"anything": 1}) == []


def test_public_tool_detail_whitelist():
    assert dr.public_tool_detail({"file_path": "/materials/" + "x" * 500}) == (
        "/materials/" + "x" * 500)[:160]
    assert dr.public_tool_detail({"content": "秘密正文"}) is None
    assert dr.public_tool_detail(None) is None


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

def test_budget_exceeded_stops_run():
    calls = [AIMessage(content="一"), AIMessage(content="二"), AIMessage(content="三")]
    agent, sink = scripted_agent(calls, budget=dr.RuntimeBudget(max_model_calls=2))
    config = {"configurable": {"thread_id": "t-budget"}}
    # Drive the graph manually: the third model call must raise.
    agent.invoke({"messages": [{"role": "user", "content": "第一轮"}]}, config=config)
    agent.invoke({"messages": [{"role": "user", "content": "第二轮"}]}, config=config)
    with pytest.raises(dr.BudgetExceededError):
        agent.invoke({"messages": [{"role": "user", "content": "第三轮"}]}, config=config)


def test_budget_counts_are_per_instance():
    budget = dr.RuntimeBudget(max_model_calls=1)
    counters_a = dr.BudgetCounters()
    counters_b = dr.BudgetCounters()
    sink = dr.ListSink()
    mw_a = dr.ObservationMiddleware(budget, counters_a, sink)
    mw_b = dr.ObservationMiddleware(budget, counters_b, sink)
    counters_a.model_calls = 5
    assert counters_b.model_calls == 0
    with pytest.raises(dr.BudgetExceededError):
        mw_a.wrap_model_call(None, lambda request: "x")
    assert mw_b.wrap_model_call(None, lambda request: "x") == "x"
    assert counters_b.model_calls == 1


# ---------------------------------------------------------------------------
# Advisory lock key
# ---------------------------------------------------------------------------

def test_thread_lock_key_stable_and_signed_int64():
    key = dr.thread_lock_key("thread-abc")
    assert key == dr.thread_lock_key("thread-abc")
    assert key != dr.thread_lock_key("thread-abd")
    assert -(2**63) <= key < 2**63
    with pytest.raises(dr.DeepRuntimeError, match="thread_id"):
        dr.thread_lock_key("  ")


# ---------------------------------------------------------------------------
# Config guards
# ---------------------------------------------------------------------------

class _Cfg:
    def __init__(self, dsn: str = "", key: str = "") -> None:
        from pydantic import SecretStr

        self.checkpoint_database_url = SecretStr(dsn)
        self.langgraph_aes_key = SecretStr(key)


def test_checkpoint_config_fail_closed():
    with pytest.raises(dr.DeepRuntimeError) as exc_info:
        dr.checkpoint_dsn(_Cfg())
    assert exc_info.value.code == "CHECKPOINT_DSN_MISSING"
    with pytest.raises(dr.DeepRuntimeError) as exc_info:
        dr.aes_key_bytes(_Cfg(key=""))
    assert exc_info.value.code == "CHECKPOINT_KEY_MISSING"
    with pytest.raises(dr.DeepRuntimeError) as exc_info:
        dr.aes_key_bytes(_Cfg(key="short"))
    assert exc_info.value.code == "CHECKPOINT_KEY_INVALID"
    assert len(dr.aes_key_bytes(_Cfg(key="0123456789abcdef"))) == 16


def test_normalize_drops_internal_and_nonmodel_metadata():
    chunk = _Chunk("摘要压缩的私有文本")
    # langchain internal-call marker (summarization middleware etc.)
    assert dr.normalize_stream_chunk("messages", (chunk, {"lc_internal_call": "token"})) == []
    # explicit lc_source marker
    assert dr.normalize_stream_chunk("messages", (chunk, {"lc_source": "summarization"})) == []
    # non-model graph nodes never produce public deltas
    assert dr.normalize_stream_chunk("messages", (chunk, {"langgraph_node": "tools"})) == []
    # the main model node passes
    events = dr.normalize_stream_chunk("messages", (chunk, {"langgraph_node": "model"}))
    assert events == [dr.PublicEvent(kind="message_delta", text="摘要压缩的私有文本")]
    # missing metadata is treated as public model stream (native shape)
    assert dr.normalize_stream_chunk("messages", (_Chunk("普通增量"), {})) != []


def test_materials_reject_backslash_and_dot_segments():
    with pytest.raises(dr.DeepRuntimeError, match="非法材料路径"):
        dr.materials_files({"..\\escape.md": "x"})
    with pytest.raises(dr.DeepRuntimeError, match="非法材料路径"):
        dr.materials_files({"a\\b.md": "x"})
    with pytest.raises(dr.DeepRuntimeError, match="非法材料路径"):
        dr.materials_files({"./rel.md": "x"})


def test_run_streaming_and_delete_require_lock():
    sink = dr.ListSink()
    unlocked = dr.CheckpointSession(None, InMemorySaver(), "t-nolock")
    agent, _ = scripted_agent([AIMessage(content="不应执行")])
    with pytest.raises(dr.DeepRuntimeError) as exc_info:
        dr.run_streaming(agent, unlocked, inputs={"messages": []}, sink=sink)
    assert exc_info.value.code == "THREAD_LOCK_REQUIRED"
    with pytest.raises(dr.DeepRuntimeError) as exc_info:
        dr.delete_thread_data(unlocked)
    assert exc_info.value.code == "THREAD_LOCK_REQUIRED"
    assert sink.events == []
