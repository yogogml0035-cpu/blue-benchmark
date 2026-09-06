"""Durable deep-agent runtime primitives (verified against deepagents 0.7.13).

This module owns the LOW-LEVEL runtime capabilities consumed by the M0 rubric
generation cutover:

* restricted agent construction — no default subagents, no ``execute``/shell,
  no ``task`` delegation, no host filesystem, no web, no cross-question store;
  materials are mounted read-only under ``/materials`` inside the thread's
  ``StateBackend``;
* public event normalization — the agent's native synchronous stream
  (``stream_mode=["messages", "updates", "custom"]``) is mapped to a
  controlled public vocabulary (stages, message deltas, tool boundaries);
  private reasoning, system prompts, credentials and raw tool payloads never
  pass through;
* PostgreSQL checkpoint session — one dedicated connection carries both the
  ``PostgresSaver`` (encrypted serializer) and the thread-level advisory lock,
  so the single-writer guarantee and the checkpoint writes share one physical
  connection for the whole execution;
* resume classification — decide between "fresh input", "resume incomplete
  run" and "re-commit completed run" without re-appending the initial input;
* model-free cleanup — delete every checkpoint row group of a thread and
  verify zero residue; never requires a working provider.

Streaming protocol choice (locked release evidence): synchronous
``stream_events(version="v3")`` exists but is decorated experimental/beta in
langgraph 1.2.11 and returns a caller-driven ``GraphRunStream``; v1/v2 dict
events are async-only (``astream_events``). The stable synchronous contract is
``stream(stream_mode=[...], durability="sync")``, which is what this module
consumes. Only ONE streaming path is maintained.

Business mapping (threads per question, public message tables, SSE, delete
workflow) belongs to the service layer, not here. Nothing in this module
registers a second production entrypoint or a compatibility switch.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import SecretStr

from langchain.agents.middleware.types import AgentMiddleware as _AgentMiddlewareBase

from app.lib.ai_runtime.model import RuntimeModelIdentity
from app.lib.settings import Settings, settings

MATERIALS_ROOT = "/materials"
WORKSPACE_ROOT = "/workspace"

# Locked SDK identities this module is verified against. Tests assert the
# installed versions so a silent dependency drift fails loudly.
VERIFIED_DEEPAGENTS_VERSION = "0.7.13"
VERIFIED_CHECKPOINT_POSTGRES_VERSION = "3.1.2"

ThreadState = Literal["new", "incomplete", "complete"]


class DeepRuntimeError(RuntimeError):
    """Safe-to-display runtime failure with a stable machine code."""

    def __init__(self, code: str, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class BudgetExceededError(DeepRuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__("RUNTIME_BUDGET_EXCEEDED", message, retryable=False)


class ThreadLockBusyError(DeepRuntimeError):
    def __init__(self, thread_id: str) -> None:
        super().__init__(
            "THREAD_LOCK_BUSY",
            f"线程 {thread_id} 已被其他执行者持有，本次不得开始模型调用或写入。",
            retryable=True,
        )


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RuntimeBudget:
    """Bounded per-run resource ceiling. Long waits are allowed; unbounded
    loops, retries and spend are not."""

    max_model_calls: int = 24
    max_tool_calls: int = 120
    max_total_seconds: float = 1800.0


@dataclass
class BudgetCounters:
    model_calls: int = 0
    tool_calls: int = 0
    started_at: float = field(default_factory=time.monotonic)

    def elapsed(self) -> float:
        return time.monotonic() - self.started_at


# ---------------------------------------------------------------------------
# Public events
# ---------------------------------------------------------------------------

PublicEventKind = Literal[
    "run_started",
    "run_resumed",
    "stage",
    "message_delta",
    "message",
    "tool_started",
    "tool_finished",
    "tool_failed",
    "interrupted",
    "run_completed",
    "run_failed",
]


@dataclass(frozen=True)
class PublicEvent:
    """One controlled public progress event.

    ``text`` carries only content authorized for the teacher-facing timeline:
    model public message fragments and deterministic stage labels. Tool events
    carry the tool name and a short whitelisted locator, never raw arguments
    or result payloads.
    """

    kind: PublicEventKind
    stage: str | None = None
    text: str | None = None
    tool: str | None = None
    detail: str | None = None

    def redacted(self) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": self.kind}
        for key in ("stage", "text", "tool", "detail"):
            value = getattr(self, key)
            if value is not None:
                data[key] = value
        return data


class ProgressSink(Protocol):
    def emit(self, event: PublicEvent) -> None: ...


class ListSink:
    """In-memory sink for tests and probes."""

    def __init__(self) -> None:
        self.events: list[PublicEvent] = []

    def emit(self, event: PublicEvent) -> None:
        self.events.append(event)


_PRIVATE_BLOCK_TYPES = {"reasoning", "thinking", "redacted_thinking", "server_tool_use"}
_PUBLIC_TOOL_ARG_FIELDS: tuple[str, ...] = ("file_path", "path", "pattern", "description")
_DETAIL_LIMIT = 160

# langchain marks middleware-internal model calls (e.g. the summarization
# middleware's own invoke) with config metadata; their tokens arrive on the
# same "messages" channel and are private context compression, never public
# teacher-facing feedback.
try:  # pragma: no cover - constant present in locked langchain 1.4.0
    from langchain.agents.middleware.internal_call_transformer import (
        INTERNAL_CALL_METADATA_KEY as _INTERNAL_CALL_KEY,
    )
except Exception:  # noqa: BLE001
    _INTERNAL_CALL_KEY = "lc_internal_call"
_INTERNAL_METADATA_SOURCES = {"summarization"}
_PUBLIC_STREAM_NODES = {"model"}


def _metadata_is_internal(metadata: Any) -> bool:
    if not isinstance(metadata, Mapping):
        return False
    if metadata.get(_INTERNAL_CALL_KEY):
        return True
    if metadata.get("lc_source") in _INTERNAL_METADATA_SOURCES:
        return True
    node = metadata.get("langgraph_node")
    if node is not None and node not in _PUBLIC_STREAM_NODES:
        return True
    return False


def _chunk_public_text(chunk: Any) -> str:
    """Public text of a message chunk; private-only chunks yield ''."""
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    else:
        text = ""
    return text


def _chunk_is_private(chunk: Any) -> bool:
    """True when a chunk carries only private reasoning, not public text."""
    if _chunk_public_text(chunk):
        return False
    content = getattr(chunk, "content", None)
    if isinstance(content, list):
        blocks = [b for b in content if isinstance(b, dict)]
        if blocks and all(b.get("type") in _PRIVATE_BLOCK_TYPES for b in blocks):
            return True
    additional = getattr(chunk, "additional_kwargs", None) or {}
    return "reasoning_content" in additional or "reasoning" in additional


def public_tool_detail(args: Mapping[str, Any] | None) -> str | None:
    """Whitelisted, truncated locator from tool arguments (never full args)."""
    if not isinstance(args, Mapping):
        return None
    for key in _PUBLIC_TOOL_ARG_FIELDS:
        value = args.get(key)
        if isinstance(value, str) and value:
            return value[:_DETAIL_LIMIT]
    return None


def normalize_stream_chunk(mode: str, payload: Any) -> list[PublicEvent]:
    """Map one native ``stream(stream_mode=[...])`` chunk to public events.

    ``messages`` yields model token deltas (private-only chunks dropped);
    ``updates`` yields deterministic node/stage markers; ``custom`` yields
    caller-emitted stage text. Tool boundaries are emitted by the observation
    middleware, which sees full requests — not by parsing partial tool-call
    JSON fragments here.
    """
    if mode == "messages":
        chunk, metadata = payload
        if _metadata_is_internal(metadata):
            return []
        if _chunk_is_private(chunk):
            return []
        text = _chunk_public_text(chunk)
        if text:
            return [PublicEvent(kind="message_delta", text=text)]
        return []

    if mode == "updates":
        if not isinstance(payload, Mapping):
            return []
        events: list[PublicEvent] = []
        for node_name in payload:
            events.append(PublicEvent(kind="stage", stage=str(node_name)))
        return events

    if mode == "custom":
        if isinstance(payload, Mapping):
            stage = str(payload.get("stage") or "custom")
            text = payload.get("text")
            return [PublicEvent(kind="stage", stage=stage,
                                text=str(text)[:_DETAIL_LIMIT] if text is not None else None)]
        return [PublicEvent(kind="stage", stage="custom", text=str(payload)[:_DETAIL_LIMIT])]

    return []


# ---------------------------------------------------------------------------
# Restricted agent construction
# ---------------------------------------------------------------------------

def restricted_profile_key(identity: RuntimeModelIdentity) -> str:
    return f"{identity.provider}:{identity.model}"


def register_restricted_profile(identity: RuntimeModelIdentity, model: Any = None) -> list[str]:
    """Register hard tool restrictions for this run (idempotent).

    Prompt text is NOT the enforcement layer: excluded tools are filtered from
    the model request and rejected at the tool-call boundary, and the default
    general-purpose subagent is disabled so ``task`` is never exposed.

    The profile registry is consulted with keys derived from the pre-built
    model instance; we register BOTH the identity key and the model-derived
    key so exclusion cannot silently miss because of derivation quirks.
    """
    from deepagents import (
        GeneralPurposeSubagentProfile,
        HarnessProfile,
        register_harness_profile,
    )
    from deepagents._models import get_model_identifier, get_model_provider

    profile = HarnessProfile(
        tool_description_overrides={},
        excluded_tools=frozenset({"execute", "task"}),
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
    )
    keys = {restricted_profile_key(identity)}
    if model is not None:
        try:
            provider = get_model_provider(model)
            identifier = get_model_identifier(model)
        except Exception:
            provider = identifier = None
        if provider and identifier and ":" not in identifier:
            keys.add(f"{provider}:{identifier}")
        elif provider and not identifier:
            # Models that expose no identifier (test fakes) can only be
            # matched by the bare provider key. Production relay models always
            # derive an exact provider:model key, so the process-global bare
            # registration is a test-only fallback, never a production path.
            keys.add(provider)
    # NOTE: the registry is process-global mutable state; exact keys only for
    # any model that exposes an identifier — a bare provider key would
    # silently reconfigure every model of that provider in the process.
    registered = sorted(keys)
    for key in registered:
        register_harness_profile(key, profile)
    return registered


def restricted_permissions() -> list[Any]:
    """Path rules: materials read-only, workspace writable, internals kept.

    Evaluated in declaration order, first match wins, unmatched calls allowed.
    The framework's internal working directories (large tool results,
    conversation-history eviction) stay writable inside the thread state —
    they are part of durable context management, not a host filesystem, and
    StateBackend never touches host paths.
    """
    from deepagents import FilesystemPermission

    return [
        FilesystemPermission(paths=[f"{MATERIALS_ROOT}/**"], operations=["write"], mode="deny"),
        FilesystemPermission(paths=[f"{MATERIALS_ROOT}/**"], operations=["read"], mode="allow"),
        FilesystemPermission(paths=[f"{WORKSPACE_ROOT}/**"], operations=["read", "write"], mode="allow"),
    ]


def materials_files(materials: Mapping[str, str]) -> dict[str, Any]:
    """Build the initial StateBackend file mapping for one question's materials.

    Keys are virtual POSIX paths under ``/materials``; values are framework
    ``FileData`` dicts (content + encoding + timestamps) — the exact shape
    ``StateBackend`` persists, so ``ls``/``read_file``/``grep`` work on seeded
    materials identically to agent-written workspace files. Callers pass only
    the current question's materials — this function performs no
    cross-question lookup and cannot widen scope.
    """
    from deepagents.backends.utils import create_file_data

    files: dict[str, Any] = {}
    for name, content in materials.items():
        clean = str(name).strip().strip("/")
        segments = clean.split("/")
        if (
            not clean
            or any(not s or s in (".", "..") or "\\" in s for s in segments)
        ):
            raise DeepRuntimeError(
                "MATERIAL_PATH_INVALID", f"非法材料路径：{name!r}", retryable=False
            )
        if not isinstance(content, str) or not content.strip():
            raise DeepRuntimeError(
                "MATERIAL_CONTENT_INVALID", f"材料正文不能为空：{name!r}", retryable=False
            )
        files[f"{MATERIALS_ROOT}/{clean}"] = create_file_data(content)
    if not files:
        raise DeepRuntimeError("MATERIALS_EMPTY", "本题材料为空，拒绝启动生成。", retryable=False)
    return files


def bound_tool_names(agent: Any) -> set[str]:
    """Names actually registered on the compiled agent's tool node."""
    node = agent.get_graph().nodes.get("tools")
    data = getattr(node, "data", None)
    registry = getattr(data, "tools_by_name", None)
    if isinstance(registry, Mapping):
        return set(registry.keys())
    raise DeepRuntimeError("RUNTIME_INTROSPECTION_FAILED", "无法检查已装配的工具列表。")


class ObservationMiddleware(_AgentMiddlewareBase):
    """Per-run class-based middleware: budget enforcement + public observation.

    Instances are created per run and never shared across threads; all mutable
    counters live on the instance. Interrupts and cancellations propagate
    untouched — counting happens around ``handler`` calls and no hook swallows
    exceptions. Tool boundary events are emitted here because this layer sees
    complete tool requests; the stream normalizer never parses partial
    tool-call JSON.
    """

    def __init__(self, budget: RuntimeBudget, counters: BudgetCounters, sink: ProgressSink) -> None:
        self._budget = budget
        self._counters = counters
        self._sink = sink

    def _check(self, what: str) -> None:
        if self._counters.model_calls > self._budget.max_model_calls:
            raise BudgetExceededError(f"模型调用超过预算（{what}）。")
        if self._counters.tool_calls > self._budget.max_tool_calls:
            raise BudgetExceededError(f"工具调用超过预算（{what}）。")
        if self._counters.elapsed() > self._budget.max_total_seconds:
            raise BudgetExceededError(f"运行时长超过预算（{what}）。")

    def before_agent(self, state: Any, runtime: Any = None) -> None:
        self._check("before_agent")
        return None

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        self._counters.model_calls += 1
        self._check("model_call")
        self._sink.emit(PublicEvent(kind="stage", stage="model_call_started",
                                    detail=f"call {self._counters.model_calls}"))
        return handler(request)

    async def awrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        self._counters.model_calls += 1
        self._check("model_call")
        self._sink.emit(PublicEvent(kind="stage", stage="model_call_started",
                                    detail=f"call {self._counters.model_calls}"))
        return await handler(request)

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        self._counters.tool_calls += 1
        self._check("tool_call")
        call = getattr(request, "tool_call", None) or {}
        name = str(call.get("name") or "tool")
        self._sink.emit(PublicEvent(kind="tool_started", tool=name,
                                    detail=public_tool_detail(call.get("args"))))
        result = handler(request)
        self._emit_tool_result(name, result)
        return result

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        self._counters.tool_calls += 1
        self._check("tool_call")
        call = getattr(request, "tool_call", None) or {}
        name = str(call.get("name") or "tool")
        self._sink.emit(PublicEvent(kind="tool_started", tool=name,
                                    detail=public_tool_detail(call.get("args"))))
        result = await handler(request)
        self._emit_tool_result(name, result)
        return result

    def _emit_tool_result(self, name: str, result: Any) -> None:
        status = getattr(result, "status", None)
        if status == "error":
            self._sink.emit(PublicEvent(kind="tool_failed", tool=name, detail="error"))
        else:
            self._sink.emit(PublicEvent(kind="tool_finished", tool=name, detail="ok"))


def build_restricted_agent(
    model: Any,
    identity: RuntimeModelIdentity,
    *,
    system_prompt: str,
    tools: Sequence[Any] = (),
    budget: RuntimeBudget,
    counters: BudgetCounters,
    sink: ProgressSink,
    checkpointer: Any,
    response_format: Any = None,
    context_schema: Any = None,
    extra_middleware: Sequence[Any] = (),
) -> Any:
    """Assemble the restricted deep agent for one run.

    ``checkpointer`` must be a real saver instance (or ``False`` in stub
    contract tests); ``store`` is deliberately never passed — there is no
    cross-question memory in M0. ``extra_middleware`` is appended after the
    observation middleware (user position in the stack).
    """
    from deepagents import create_deep_agent
    from deepagents.backends import StateBackend

    register_restricted_profile(identity, model)
    kwargs: dict[str, Any] = {
        "model": model,
        "tools": list(tools),
        "system_prompt": system_prompt,
        "middleware": [ObservationMiddleware(budget, counters, sink), *extra_middleware],
        "backend": StateBackend(),
        "permissions": restricted_permissions(),
        "checkpointer": checkpointer,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format
    if context_schema is not None:
        kwargs["context_schema"] = context_schema
    return create_deep_agent(**kwargs)


# ---------------------------------------------------------------------------
# Checkpoint session: one connection = saver + advisory lock
# ---------------------------------------------------------------------------

def _secret_bytes(value: Any) -> str:
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return str(value or "")


def aes_key_bytes(config: Settings) -> bytes:
    key = _secret_bytes(config.langgraph_aes_key)
    if not key:
        raise DeepRuntimeError(
            "CHECKPOINT_KEY_MISSING",
            "LANGGRAPH_AES_KEY 未配置，拒绝以明文 serializer 落库。",
            retryable=False,
        )
    raw = key.encode()
    if len(raw) not in (16, 24, 32):
        raise DeepRuntimeError(
            "CHECKPOINT_KEY_INVALID",
            "LANGGRAPH_AES_KEY 必须是 16/24/32 字节。",
            retryable=False,
        )
    return raw


def checkpoint_dsn(config: Settings) -> str:
    dsn = _secret_bytes(config.checkpoint_database_url)
    if not dsn:
        raise DeepRuntimeError(
            "CHECKPOINT_DSN_MISSING", "CHECKPOINT_DATABASE_URL 未配置。", retryable=False
        )
    return dsn


def build_saver(conn: Any, config: Settings = settings) -> Any:
    """PostgresSaver on an existing connection with the encrypted serializer."""
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.checkpoint.serde.encrypted import EncryptedSerializer

    serde = EncryptedSerializer.from_pycryptodome_aes(key=aes_key_bytes(config))
    return PostgresSaver(conn, serde=serde)


def thread_lock_key(thread_id: str) -> int:
    """Stable signed-int64 advisory lock key derived from the thread id."""
    clean = str(thread_id).strip()
    if not clean:
        raise DeepRuntimeError("THREAD_ID_INVALID", "thread_id 不能为空。", retryable=False)
    digest = hashlib.sha256(clean.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


class CheckpointSession:
    """Owns one dedicated connection, its saver and the thread advisory lock.

    The lock and all checkpoint writes share this physical connection for the
    whole execution; when the connection dies, the lock and the writer die
    together — a stale writer cannot switch to a fresh unlocked connection and
    keep writing.
    """

    def __init__(self, conn: Any, saver: Any, thread_id: str) -> None:
        self.conn = conn
        self.saver = saver
        self.thread_id = thread_id
        self._lock_held = False
        self._closed = False

    @property
    def lock_held(self) -> bool:
        return self._lock_held

    def acquire_lock(self) -> None:
        if self._lock_held:
            return
        with self.conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (thread_lock_key(self.thread_id),))
            row = cur.fetchone()
        if not row or not row[0]:
            raise ThreadLockBusyError(self.thread_id)
        self._lock_held = True

    def release_lock(self) -> None:
        if not self._lock_held or self._closed:
            return
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (thread_lock_key(self.thread_id),))
        except Exception:  # noqa: BLE001
            # The connection is already dead; PostgreSQL released the session
            # advisory lock when the connection dropped. Swallowing this keeps
            # the ORIGINAL run failure propagating instead of masking it with
            # a connection error during teardown.
            pass
        finally:
            self._lock_held = False

    def thread_config(self, **extra: Any) -> dict[str, Any]:
        configurable: dict[str, Any] = {"thread_id": self.thread_id}
        configurable.update(extra)
        return {"configurable": configurable}

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.release_lock()
        finally:
            self._closed = True
            try:
                self.conn.close()
            except Exception:  # noqa: BLE001
                pass  # already-dead connection must not mask the real error

    def __enter__(self) -> "CheckpointSession":
        self.acquire_lock()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def open_session(
    thread_id: str,
    config: Settings = settings,
    *,
    run_setup: bool = True,
) -> CheckpointSession:
    """Open the dedicated connection, prepare schema, take the thread lock.

    ``setup()`` is an explicit idempotent preparation step for isolated
    environments; production deployment runs it as a deliberate step, not on
    page load. Fails loudly when the checkpoint database or key is missing —
    never falls back to memory. The caller owns ``close()``.
    """
    import psycopg

    dsn = checkpoint_dsn(config)
    conn = psycopg.connect(dsn, autocommit=True)
    try:
        saver = build_saver(conn, config)
        if run_setup:
            saver.setup()
        session = CheckpointSession(conn, saver, thread_id)
        try:
            session.acquire_lock()
        except BaseException:
            conn.close()
            raise
        return session
    except BaseException:
        if not conn.closed:
            conn.close()
        raise


@contextmanager
def open_checkpoint_session(
    thread_id: str,
    config: Settings = settings,
    *,
    run_setup: bool = True,
) -> Iterator[CheckpointSession]:
    """Context-manager form of :func:`open_session`."""
    session = open_session(thread_id, config, run_setup=run_setup)
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Thread state classification and cleanup
# ---------------------------------------------------------------------------

def classify_thread_state(agent: Any, config: Mapping[str, Any]) -> ThreadState:
    """Classify a thread for the resume decision, without touching a model.

    * ``new``: no checkpoint — the caller must submit the initial input.
    * ``incomplete``: checkpoint exists with pending nodes (crash, interrupt)
      — resume from the saved execution point with ``inputs=None``.
    * ``complete``: the graph ran to completion — re-verify the stored result
      and retry only the business commit.
    """
    state = agent.get_state(config)
    values = getattr(state, "values", None) or {}
    if not values:
        return "new"
    return "incomplete" if tuple(getattr(state, "next", ()) or ()) else "complete"


def thread_data_residue(conn: Any, thread_id: str) -> dict[str, int]:
    """Count every checkpoint row group belonging to one thread."""
    counts: dict[str, int] = {}
    queries = {
        "checkpoints": "SELECT count(*) FROM checkpoints WHERE thread_id = %s",
        "checkpoint_writes": "SELECT count(*) FROM checkpoint_writes WHERE thread_id = %s",
        "checkpoint_blobs": "SELECT count(*) FROM checkpoint_blobs WHERE thread_id = %s",
    }
    for table, sql in queries.items():
        with conn.cursor() as cur:
            cur.execute(sql, (thread_id,))
            row = cur.fetchone()
        counts[table] = int(row[0]) if row else 0
    return counts


def _require_lock(session: "CheckpointSession", operation: str) -> None:
    if not session.lock_held:
        raise DeepRuntimeError(
            "THREAD_LOCK_REQUIRED",
            f"线程 {session.thread_id} 未持有单写者锁，拒绝执行 {operation}。",
            retryable=True,
        )


def delete_thread_data(session: "CheckpointSession") -> dict[str, int]:
    """Delete ALL checkpoint data of the session's thread; verify zero residue.

    Requires the session's advisory lock: cleanup is a writer on the thread
    and must obey the same single-writer rule as execution, so a concurrent
    executor can never write back after the residue check.

    Model-free by construction: this path never initializes a provider, so a
    broken AI configuration can never block cleanup.
    """
    _require_lock(session, "线程删除")
    session.saver.delete_thread(session.thread_id)
    residue = thread_data_residue(session.conn, session.thread_id)
    if any(value != 0 for value in residue.values()):
        raise DeepRuntimeError(
            "THREAD_CLEANUP_INCOMPLETE",
            f"线程 {session.thread_id} 清理后仍有残留：{residue}",
            retryable=True,
        )
    return residue


# ---------------------------------------------------------------------------
# Streaming execution
# ---------------------------------------------------------------------------

STREAM_MODES: tuple[str, ...] = ("messages", "updates", "custom")


def run_streaming(
    agent: Any,
    session: CheckpointSession,
    *,
    inputs: Any,
    sink: ProgressSink,
    durability: str = "sync",
    allow_followup: bool = False,
) -> Any:
    """Execute one run, pushing normalized public events into ``sink``.

    ``inputs`` is the fresh initial state for a new run, ``None`` to resume an
    incomplete checkpoint without re-appending the initial input, or a
    ``Command(resume=...)`` to answer a parked interrupt.
    ``durability="sync"`` makes each step's checkpoint durable before the next
    step starts; the value is passed to the native streaming call, not merely
    documented. Returns the final graph state values.

    Interrupts are NOT exceptions: the graph parks, ``run_completed`` is not
    emitted, and the caller inspects ``inspect_interrupt`` to project the
    waiting state.

    A fresh-input mapping against a thread that ALREADY has a checkpoint is
    refused (THREAD_INPUT_CONFLICT): resuming must use ``inputs=None`` or a
    ``Command(resume=...)``, never a re-submitted initial input. This makes
    "restore must not duplicate the initial input" a mechanical guarantee.
    """
    from langgraph.types import Command

    _require_lock(session, "流式执行")
    config = session.thread_config()
    is_fresh_input = (
        inputs is not None and not isinstance(inputs, Command) and not allow_followup
    )
    if is_fresh_input:
        existing = agent.get_state(config)
        if getattr(existing, "values", None):
            raise DeepRuntimeError(
                "THREAD_INPUT_CONFLICT",
                f"线程 {session.thread_id} 已有检查点，拒绝重复提交初始输入；"
                "续跑请使用 inputs=None 或 Command(resume=...)。",
                retryable=False,
            )
    saw_any = False
    for mode, payload in agent.stream(
        inputs, config=config, stream_mode=list(STREAM_MODES), durability=durability
    ):
        saw_any = True
        for event in normalize_stream_chunk(mode, payload):
            sink.emit(event)
    if not saw_any:
        raise DeepRuntimeError("RUNTIME_NO_EVENTS", "运行没有产生任何事件。")
    interrupted, payloads = inspect_interrupt(agent, session)
    if interrupted:
        sink.emit(PublicEvent(kind="interrupted",
                              detail=f"{len(payloads)} pending"))
    else:
        sink.emit(PublicEvent(kind="run_completed"))
    state = agent.get_state(config)
    return dict(getattr(state, "values", None) or {})


def inspect_interrupt(agent: Any, session: CheckpointSession) -> tuple[bool, list[Any]]:
    """Whether the thread is parked on an interrupt, and the payloads."""
    state = agent.get_state(session.thread_config())
    payloads: list[Any] = []
    for task in getattr(state, "tasks", ()) or ():
        for interrupt in getattr(task, "interrupts", ()) or ():
            payloads.append(getattr(interrupt, "value", interrupt))
    return bool(payloads), payloads


def final_structured_response(agent: Any, session: CheckpointSession) -> Any:
    """Read the finished graph's structured response from persisted state."""
    state = agent.get_state(session.thread_config())
    values = getattr(state, "values", None) or {}
    return values.get("structured_response")


def final_files(agent: Any, session: CheckpointSession) -> dict[str, Any]:
    """Read the finished graph's workspace/material files from state."""
    state = agent.get_state(session.thread_config())
    values = getattr(state, "values", None) or {}
    return dict(values.get("files") or {})
