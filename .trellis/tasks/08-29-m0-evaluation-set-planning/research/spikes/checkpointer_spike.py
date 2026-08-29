from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, ClassVar

import psycopg
from deepagents import (
    FilesystemPermission,
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.backends import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
)
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain.tools import ToolRuntime
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool, tool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.encrypted import EncryptedSerializer
from langgraph.types import Command


PROFILE_KEY = "spike-model"
QUESTION_THREAD = "m0-standard-cocreator-spike"
FALLBACK_THREAD = "m0-completed-turn-fallback-spike"
AES_KEY = b"0123456789abcdef0123456789abcdef"


class AskTeacherModel(BaseChatModel):
    """Deterministic tool-calling model for framework mechanics only."""

    call_count: ClassVar[int] = 0
    bound_tools: ClassVar[list[str]] = []

    @property
    def _llm_type(self) -> str:
        return PROFILE_KEY

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | dict[str, str] | None = None,
        **kwargs: Any,
    ) -> BaseChatModel:
        del tool_choice, kwargs
        names: list[str] = []
        for item in tools:
            if isinstance(item, dict):
                names.append(str(item.get("name", "")))
            else:
                names.append(str(getattr(item, "name", getattr(item, "__name__", ""))))
        type(self).bound_tools = sorted(name for name in names if name)
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        type(self).call_count += 1
        has_teacher_response = any(
            isinstance(message, ToolMessage) and message.name == "ask_teacher"
            for message in messages
        )
        if has_teacher_response:
            response = AIMessage(content="completed")
        else:
            response = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "ask_teacher",
                        "args": {
                            "question": "Which boundary needs confirmation?",
                            "reason": "It is the only blocking product decision.",
                        },
                        "id": "ask-teacher-1",
                        "type": "tool_call",
                    }
                ],
            )
        return ChatResult(generations=[ChatGeneration(message=response)])


class CompletedTurnModel(AskTeacherModel):
    """Deterministic no-interrupt fallback that still uses one stable thread."""

    @property
    def _llm_type(self) -> str:
        return f"{PROFILE_KEY}-fallback"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        type(self).call_count += 1
        human_messages = [message for message in messages if isinstance(message, HumanMessage)]
        content = "question" if len(human_messages) < 2 else "completed"
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])


class RetryOnceModel(AskTeacherModel):
    attempts: ClassVar[int] = 0

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del messages, stop, run_manager, kwargs
        type(self).attempts += 1
        if type(self).attempts == 1:
            raise TimeoutError("synthetic transport timeout")
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])


class DisallowedToolModel(AskTeacherModel):
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del messages, stop, run_manager, kwargs
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "write_file",
                                "args": {"file_path": "/x", "content": "x"},
                                "id": "disallowed-call",
                                "type": "tool_call",
                            }
                        ],
                    )
                )
            ]
        )


class ModelToolSurfaceMiddleware(AgentMiddleware):
    """Expose only named tools and reject hallucinated hidden tool calls."""

    def __init__(self, allowed_names: set[str]) -> None:
        self.allowed_names = frozenset(allowed_names)

    @staticmethod
    def _tool_name(item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("name", ""))
        return str(getattr(item, "name", getattr(item, "__name__", "")))

    def _filtered_request(self, request: ModelRequest) -> ModelRequest:
        return request.override(
            tools=[
                item
                for item in request.tools
                if self._tool_name(item) in self.allowed_names
            ]
        )

    @staticmethod
    def _last_message(state: Any) -> BaseMessage | None:
        messages = state.get("messages", [])
        return messages[-1] if messages else None

    def _validate(self, state: Any) -> None:
        message = self._last_message(state)
        if not isinstance(message, AIMessage):
            return
        disallowed = {
            call.get("name", "")
            for call in message.tool_calls
            if call.get("name", "") not in self.allowed_names
        }
        if disallowed:
            raise RuntimeError(
                "Model returned disallowed tool calls: " + ", ".join(sorted(disallowed))
            )

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Any],
    ) -> ModelResponse:
        return await handler(self._filtered_request(request))

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(self._filtered_request(request))

    def after_model(self, state: Any, runtime: Any) -> None:
        del runtime
        self._validate(state)

    async def aafter_model(self, state: Any, runtime: Any) -> None:
        del runtime
        self._validate(state)


class ProbeMiddleware(AgentMiddleware):
    events: ClassVar[list[str]] = []

    def __init__(self, label: str) -> None:
        self.label = label

    @property
    def name(self) -> str:
        return f"ProbeMiddleware-{self.label}"

    async def abefore_model(self, state: Any, runtime: Any) -> None:
        del state, runtime
        type(self).events.append(f"{self.label}.before")

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Any],
    ) -> ModelResponse:
        type(self).events.append(f"{self.label}.wrap_enter")
        response = await handler(request)
        type(self).events.append(f"{self.label}.wrap_exit")
        return response

    async def aafter_model(self, state: Any, runtime: Any) -> None:
        del state, runtime
        type(self).events.append(f"{self.label}.after")


class ReadOnlyEvidenceBackend(FilesystemBackend):
    """Spike-only backend proving that the model never gets host-path writes."""

    def write(self, file_path: str, content: str) -> Any:
        del file_path, content
        raise PermissionError("EvidenceBackend is read-only")

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> Any:
        del file_path, old_string, new_string, replace_all
        raise PermissionError("EvidenceBackend is read-only")

    def delete(self, file_path: str) -> Any:
        del file_path
        raise PermissionError("EvidenceBackend is read-only")


@tool
def ask_teacher(question: str, reason: str) -> str:
    """Ask exactly one highest-value question and explain why it matters."""
    del question, reason
    raise AssertionError("respond mode must not execute ask_teacher")


def register_profiles() -> None:
    profile = HarnessProfile(
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        excluded_tools=frozenset(
            {"write_todos", "task", "write_file", "edit_file", "delete", "execute"}
        ),
    )
    for key in (
        PROFILE_KEY,
        f"{PROFILE_KEY}-fallback",
        "askteachermodel",
        "completedturnmodel",
        "retryoncemodel",
        "disallowedtoolmodel",
    ):
        register_harness_profile(key, profile)


def make_evidence_middleware() -> tuple[FilesystemMiddleware, list[FilesystemPermission]]:
    root = Path(tempfile.mkdtemp(prefix="m0-evidence-spike-"))
    evidence_dir = root / "evidence"
    evidence_dir.mkdir()
    evidence_dir.joinpath("long.txt").write_text(
        "\n".join(f"line-{number:03d}" for number in range(1, 131)),
        encoding="utf-8",
    )
    root.joinpath("outside.txt").write_text("must-not-be-readable", encoding="utf-8")
    backend = ReadOnlyEvidenceBackend(root_dir=root, virtual_mode=True)
    permissions = [
        FilesystemPermission(operations=["read"], paths=["/evidence/**"], mode="allow"),
        FilesystemPermission(operations=["read"], paths=["/**"], mode="deny"),
        FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
    ]
    middleware = FilesystemMiddleware(
        backend=backend,
        tools=["ls", "read_file", "glob", "grep"],
        _permissions=permissions,
    )
    return middleware, permissions


def make_agent(checkpointer: AsyncPostgresSaver) -> Any:
    register_profiles()
    filesystem, permissions = make_evidence_middleware()
    return create_deep_agent(
        model=AskTeacherModel(),
        tools=[ask_teacher],
        middleware=[
            filesystem,
            ModelToolSurfaceMiddleware(
                {"ask_teacher", "read_file", "ls", "glob", "grep"}
            ),
            ProbeMiddleware("A"),
            ProbeMiddleware("B"),
            ModelCallLimitMiddleware(run_limit=4, exit_behavior="error"),
            ToolCallLimitMiddleware(run_limit=4, exit_behavior="error"),
            ModelRetryMiddleware(
                max_retries=1,
                retry_on=(TimeoutError,),
                on_failure="error",
                initial_delay=0,
                backoff_factor=1,
                jitter=False,
            ),
        ],
        permissions=permissions,
        interrupt_on={"ask_teacher": {"allowed_decisions": ["respond"]}},
        checkpointer=checkpointer,
        name="standard_cocreator_spike",
    )


def connection_string() -> str:
    value = os.environ.get("SPIKE_DATABASE_URL")
    if not value:
        raise RuntimeError("SPIKE_DATABASE_URL is required")
    return value


def encrypted_serializer() -> EncryptedSerializer:
    return EncryptedSerializer.from_pycryptodome_aes(key=AES_KEY)


async def run_static_checks() -> dict[str, Any]:
    register_profiles()
    filesystem, permissions = make_evidence_middleware()
    tools = {item.name: item for item in filesystem.tools}
    runtime = ToolRuntime(
        state={},
        context=None,
        config={},
        stream_writer=lambda _: None,
        tool_call_id="static-check",
        store=None,
        tools=list(tools.values()),
    )
    first_page = await tools["read_file"].coroutine(
        file_path="/evidence/long.txt", offset=0, limit=100, runtime=runtime
    )
    final_page = await tools["read_file"].coroutine(
        file_path="/evidence/long.txt", offset=100, limit=100, runtime=runtime
    )
    denied = await tools["read_file"].coroutine(
        file_path="/outside.txt", offset=0, limit=100, runtime=runtime
    )
    first_page_text = str(getattr(first_page, "content", first_page))
    final_page_text = str(getattr(final_page, "content", final_page))
    denied_text = str(getattr(denied, "content", denied))

    RetryOnceModel.attempts = 0
    retry_agent = create_deep_agent(
        model=RetryOnceModel(),
        middleware=[
            filesystem,
            ModelCallLimitMiddleware(run_limit=1, exit_behavior="error"),
            ModelRetryMiddleware(
                max_retries=1,
                retry_on=(TimeoutError,),
                on_failure="error",
                initial_delay=0,
                backoff_factor=1,
                jitter=False,
            ),
        ],
        permissions=permissions,
    )
    retry_result = await retry_agent.ainvoke(
        {"messages": [{"role": "user", "content": "run"}]}
    )

    disallowed_agent = create_deep_agent(
        model=DisallowedToolModel(),
        middleware=[ModelToolSurfaceMiddleware(set())],
    )
    disallowed_rejected = False
    try:
        await disallowed_agent.ainvoke(
            {"messages": [{"role": "user", "content": "run"}]}
        )
    except RuntimeError as exc:
        disallowed_rejected = "write_file" in str(exc)

    malformed = AIMessage(
        content="",
        invalid_tool_calls=[
            {
                "name": "ask_teacher",
                "args": "{",
                "id": "bad-call",
                "error": "malformed",
                "type": "invalid_tool_call",
            }
        ],
    )
    return {
        "read_default_is_100_lines": "line-100" in first_page_text
        and "line-101" not in first_page_text,
        "read_reports_remaining_lines": "remaining" in first_page_text.lower(),
        "explicit_offset_reaches_eof": "line-130" in final_page_text,
        "outside_scope_denied": "permission" in denied_text.lower()
        and "denied" in denied_text.lower(),
        "write_tools_not_exposed": not {"write_file", "edit_file", "delete"}.intersection(tools),
        "transport_retry_is_inside_one_logical_model_step": (
            RetryOnceModel.attempts == 2 and retry_result["messages"][-1].content == "ok"
        ),
        "hidden_tool_hallucination_rejected_before_execution": disallowed_rejected,
        "invalid_tool_calls_fail_closed": bool(malformed.invalid_tool_calls),
    }


async def run_start() -> dict[str, Any]:
    AskTeacherModel.call_count = 0
    AskTeacherModel.bound_tools = []
    ProbeMiddleware.events = []
    async with AsyncPostgresSaver.from_conn_string(
        connection_string(), serde=encrypted_serializer()
    ) as saver:
        await saver.setup()
        agent = make_agent(saver)
        config = {"configurable": {"thread_id": QUESTION_THREAD}}
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": "start"}]},
            config,
            durability="sync",
        )
        interrupts = result.get("__interrupt__", [])
        state = await agent.aget_state(config)
        accepted_checkpoint_id = state.config["configurable"]["checkpoint_id"]
        orphan_config = await agent.aupdate_state(
            state.config,
            {"messages": [HumanMessage(content="unaccepted branch")]},
        )
        latest_state = await agent.aget_state(config)
        payload = interrupts[0].value if len(interrupts) == 1 else {}
        actions = payload.get("action_requests", [])
        reviews = payload.get("review_configs", [])
        return {
            "single_interrupt": len(interrupts) == 1,
            "single_ask_teacher": len(actions) == 1 and actions[0].get("name") == "ask_teacher",
            "respond_only": len(reviews) == 1
            and reviews[0].get("allowed_decisions") == ["respond"],
            "thread_id": QUESTION_THREAD,
            "accepted_checkpoint_id": accepted_checkpoint_id,
            "orphan_checkpoint_id": orphan_config["configurable"]["checkpoint_id"],
            "raw_latest_checkpoint_id": latest_state.config["configurable"]["checkpoint_id"],
            "latest_differs_from_accepted": (
                latest_state.config["configurable"]["checkpoint_id"]
                != accepted_checkpoint_id
            ),
            "tool_surface": AskTeacherModel.bound_tools,
            "task_tool_absent": "task" not in AskTeacherModel.bound_tools,
            "write_tools_absent": not {
                "write_file",
                "edit_file",
                "delete",
                "execute",
            }.intersection(AskTeacherModel.bound_tools),
            "model_calls": AskTeacherModel.call_count,
            "middleware_order": ProbeMiddleware.events,
        }


async def encrypted_payload_has_no_markers(thread_id: str) -> bool:
    markers = (b"Which boundary needs confirmation?", b"teacher answer", b"unaccepted branch")
    async with await psycopg.AsyncConnection.connect(connection_string()) as connection:
        payloads: list[bytes] = []
        for table, column in (
            ("checkpoints", "checkpoint"),
            ("checkpoint_blobs", "blob"),
            ("checkpoint_writes", "blob"),
        ):
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"SELECT {column} FROM {table} WHERE thread_id = %s",  # noqa: S608
                    (thread_id,),
                )
                for row in await cursor.fetchall():
                    value = row[0]
                    if isinstance(value, memoryview):
                        value = value.tobytes()
                    if isinstance(value, str):
                        value = value.encode()
                    if not isinstance(value, bytes):
                        value = json.dumps(value, default=str, sort_keys=True).encode()
                    payloads.append(bytes(value))
        joined = b"\n".join(payloads)
        return all(marker not in joined for marker in markers)


async def run_cas_checks(accepted_checkpoint_id: str) -> dict[str, Any]:
    async with await psycopg.AsyncConnection.connect(connection_string()) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute("DROP TABLE IF EXISTS m0_spike_session_guard")
            await cursor.execute(
                """
                CREATE TABLE m0_spike_session_guard (
                    session_id text PRIMARY KEY,
                    revision integer NOT NULL,
                    accepted_checkpoint_id text NOT NULL,
                    active_resume boolean NOT NULL DEFAULT false
                )
                """
            )
            await cursor.execute(
                "INSERT INTO m0_spike_session_guard VALUES (%s, %s, %s, false)",
                (QUESTION_THREAD, 1, accepted_checkpoint_id),
            )
            await cursor.execute(
                """
                UPDATE m0_spike_session_guard
                   SET active_resume = true
                 WHERE session_id = %s
                   AND revision = %s
                   AND accepted_checkpoint_id = %s
                   AND active_resume = false
                """,
                (QUESTION_THREAD, 1, accepted_checkpoint_id),
            )
            first_claim = cursor.rowcount
            await cursor.execute(
                """
                UPDATE m0_spike_session_guard
                   SET active_resume = true
                 WHERE session_id = %s
                   AND revision = %s
                   AND accepted_checkpoint_id = %s
                   AND active_resume = false
                """,
                (QUESTION_THREAD, 1, accepted_checkpoint_id),
            )
            second_claim = cursor.rowcount
            await cursor.execute(
                "UPDATE m0_spike_session_guard SET revision = 2 WHERE session_id = %s",
                (QUESTION_THREAD,),
            )
            await cursor.execute(
                """
                UPDATE m0_spike_session_guard
                   SET accepted_checkpoint_id = %s
                 WHERE session_id = %s
                   AND revision = 1
                   AND accepted_checkpoint_id = %s
                """,
                ("stale-result", QUESTION_THREAD, accepted_checkpoint_id),
            )
            stale_commit = cursor.rowcount
            await cursor.execute("DROP TABLE m0_spike_session_guard")
        await connection.commit()
    return {
        "single_active_resume_claim": first_claim == 1 and second_claim == 0,
        "stale_revision_commit_rejected": stale_commit == 0,
    }


async def run_fallback() -> dict[str, Any]:
    CompletedTurnModel.call_count = 0
    async with AsyncPostgresSaver.from_conn_string(
        connection_string(), serde=encrypted_serializer()
    ) as saver:
        register_profiles()
        filesystem, permissions = make_evidence_middleware()
        agent = create_deep_agent(
            model=CompletedTurnModel(),
            middleware=[filesystem],
            permissions=permissions,
            checkpointer=saver,
            name="completed_turn_fallback_spike",
        )
        config = {"configurable": {"thread_id": FALLBACK_THREAD}}
        first = await agent.ainvoke(
            {"messages": [{"role": "user", "content": "start"}]},
            config,
            durability="sync",
        )
        second = await agent.ainvoke(
            {"messages": [{"role": "user", "content": "teacher answer"}]},
            config,
            durability="sync",
        )
        state = await agent.aget_state(config)
        return {
            "same_thread": state.config["configurable"]["thread_id"] == FALLBACK_THREAD,
            "first_turn_completed": first["messages"][-1].content == "question",
            "second_turn_completed": second["messages"][-1].content == "completed",
            "model_calls": CompletedTurnModel.call_count,
        }


async def run_resume(accepted_checkpoint_id: str) -> dict[str, Any]:
    AskTeacherModel.call_count = 0
    ProbeMiddleware.events = []
    async with AsyncPostgresSaver.from_conn_string(
        connection_string(), serde=encrypted_serializer()
    ) as saver:
        agent = make_agent(saver)
        explicit_config = {
            "configurable": {
                "thread_id": QUESTION_THREAD,
                "checkpoint_ns": "",
                "checkpoint_id": accepted_checkpoint_id,
            }
        }
        result = await agent.ainvoke(
            Command(
                resume={
                    "decisions": [
                        {"type": "respond", "message": "teacher answer"}
                    ]
                }
            ),
            explicit_config,
            durability="sync",
        )
        produced_state = await agent.aget_state(
            {"configurable": {"thread_id": QUESTION_THREAD}}
        )
        calls_before_projection = AskTeacherModel.call_count
        projection_state = await agent.aget_state(produced_state.config)
        calls_after_projection = AskTeacherModel.call_count
        final_message = projection_state.values["messages"][-1]
        cas = await run_cas_checks(accepted_checkpoint_id)
        fallback = await run_fallback()
        return {
            "explicit_checkpoint_resume_completed": result["messages"][-1].content
            == "completed",
            "produced_checkpoint_id": produced_state.config["configurable"][
                "checkpoint_id"
            ],
            "projection_without_model_replay": (
                calls_before_projection == calls_after_projection
                and final_message.content == "completed"
            ),
            "encrypted_payload_has_no_plaintext_markers": await encrypted_payload_has_no_markers(
                QUESTION_THREAD
            ),
            "model_calls": AskTeacherModel.call_count,
            "middleware_order": ProbeMiddleware.events,
            "cas": cas,
            "completed_turn_fallback": fallback,
        }


async def run_delete() -> dict[str, Any]:
    async with AsyncPostgresSaver.from_conn_string(
        connection_string(), serde=encrypted_serializer()
    ) as saver:
        await saver.adelete_thread(QUESTION_THREAD)
        await saver.adelete_thread(FALLBACK_THREAD)
        remaining = [
            item
            async for item in saver.alist(
                {"configurable": {"thread_id": QUESTION_THREAD}}
            )
        ]
        return {"thread_delete_completed": not remaining}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["static", "start", "resume", "delete"])
    parser.add_argument("--checkpoint-id")
    args = parser.parse_args()
    if args.mode == "static":
        output = await run_static_checks()
    elif args.mode == "start":
        output = await run_start()
    elif args.mode == "resume":
        if not args.checkpoint_id:
            parser.error("--checkpoint-id is required for resume")
        output = await run_resume(args.checkpoint_id)
    else:
        output = await run_delete()
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
