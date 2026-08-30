from __future__ import annotations

import argparse
import json
import os
from typing import Any

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from langchain.agents.structured_output import ToolStrategy
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import BaseModel, Field, SecretStr

from checkpointer_spike import ModelToolSurfaceMiddleware


class Gap(BaseModel):
    code: str
    blocking: bool


class Review(BaseModel):
    title: str
    confidence: int = Field(ge=0, le=100)
    gaps: list[Gap]


@tool
def inspect_evidence(file_id: str) -> str:
    """Inspect one evidence file by its server-side identifier."""
    del file_id
    return "verified"


@tool
def ask_teacher(question: str, reason: str) -> str:
    """Ask exactly one highest-value question and explain why it matters."""
    del question, reason
    raise AssertionError("respond mode must not execute ask_teacher")


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def make_model(*, include_temperature: bool = False, max_tokens: int = 384) -> ChatAnthropic:
    token = required_env("SPIKE_ANTHROPIC_API_KEY")
    kwargs: dict[str, Any] = {
        "model": required_env("SPIKE_MODEL_ID"),
        "api_key": SecretStr(token),
        "base_url": required_env("SPIKE_ANTHROPIC_BASE_URL"),
        "default_headers": {"Authorization": f"Bearer {token}"},
        "max_tokens": max_tokens,
        "timeout": 60,
        "max_retries": 0,
    }
    if include_temperature:
        kwargs["temperature"] = 0
    return ChatAnthropic(**kwargs)


def register_profile() -> None:
    model_id = required_env("SPIKE_MODEL_ID")
    profile = HarnessProfile(
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        excluded_tools=frozenset(
            {
                "ls",
                "read_file",
                "write_file",
                "edit_file",
                "delete",
                "glob",
                "grep",
                "execute",
                "write_todos",
                "task",
            }
        ),
    )
    register_harness_profile("anthropic", profile)
    register_harness_profile(f"anthropic:{model_id}", profile)


def error_type(call: Any) -> str | None:
    try:
        call()
    except Exception as exc:  # noqa: BLE001 - the matrix records adapter failures
        return type(exc).__name__
    return None


def run_matrix(*, negative_checks: bool) -> dict[str, Any]:
    register_profile()
    model = make_model()
    plain = model.invoke("Reply with OK only.")

    normal_tools = model.bind_tools([inspect_evidence])
    normal_call = normal_tools.invoke(
        "Call inspect_evidence with file_id sample-1. Do not answer directly."
    )
    forced_call = model.bind_tools(
        [inspect_evidence], tool_choice="inspect_evidence"
    ).invoke("Inspect sample-1.")
    if normal_call.tool_calls:
        call = normal_call.tool_calls[0]
        roundtrip = normal_tools.invoke(
            [
                HumanMessage(content="Inspect sample-1."),
                normal_call,
                ToolMessage(
                    content="verified",
                    tool_call_id=call["id"],
                    name="inspect_evidence",
                ),
            ]
        )
    else:
        roundtrip = AIMessage(content="", invalid_tool_calls=[])

    empty = model.bind_tools([]).invoke("Reply with OK only.")
    function_output = model.with_structured_output(
        Review, include_raw=True, method="function_calling"
    ).invoke(
        "Return title 测试, confidence 90, and one nonblocking gap with code G1."
    )

    tool_agent = create_deep_agent(
        model=model,
        middleware=[ModelToolSurfaceMiddleware({"Review"})],
        response_format=ToolStrategy(Review),
        system_prompt="Return exactly the requested structured review.",
    )
    tool_agent_output = tool_agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Return title 测试, confidence 90, and nonblocking G1.",
                }
            ]
        }
    )

    hitl_agent = create_deep_agent(
        model=model,
        tools=[ask_teacher],
        middleware=[ModelToolSurfaceMiddleware({"ask_teacher", "Review"})],
        interrupt_on={"ask_teacher": {"allowed_decisions": ["respond"]}},
        response_format=ToolStrategy(Review),
        checkpointer=InMemorySaver(),
        system_prompt=(
            "First call ask_teacher exactly once. After its response, return Review "
            "with title 测试, confidence 90, and one nonblocking G1."
        ),
    )
    config = {"configurable": {"thread_id": "provider-hitl-spike"}}
    first = hitl_agent.invoke(
        {"messages": [{"role": "user", "content": "Start."}]},
        config,
        durability="sync",
    )
    interrupts = first.get("__interrupt__", [])
    snapshot = hitl_agent.get_state(config)
    payload = interrupts[0].value if len(interrupts) == 1 else {}
    actions = payload.get("action_requests", [])
    reviews = payload.get("review_configs", [])
    resumed = hitl_agent.invoke(
        Command(
            resume={
                "decisions": [
                    {"type": "respond", "message": "Confirmed; produce the review."}
                ]
            }
        ),
        snapshot.config,
        durability="sync",
    )

    output: dict[str, Any] = {
        "plain_non_streaming": bool(plain.content) and not plain.invalid_tool_calls,
        "normal_tool_call": len(normal_call.tool_calls) == 1
        and normal_call.tool_calls[0]["name"] == "inspect_evidence"
        and not normal_call.invalid_tool_calls,
        "forced_tool_call": len(forced_call.tool_calls) == 1
        and forced_call.tool_calls[0]["name"] == "inspect_evidence"
        and not forced_call.invalid_tool_calls,
        "tool_message_roundtrip": bool(roundtrip.content)
        and not roundtrip.invalid_tool_calls,
        "empty_tools": bool(empty.content) and not empty.invalid_tool_calls,
        "function_calling_nested_schema": isinstance(
            function_output.get("parsed"), Review
        )
        and function_output.get("parsing_error") is None,
        "deep_agent_tool_strategy": isinstance(
            tool_agent_output.get("structured_response"), Review
        ),
        "hitl_single_ask_teacher": len(interrupts) == 1
        and len(actions) == 1
        and actions[0].get("name") == "ask_teacher",
        "hitl_respond_only": len(reviews) == 1
        and reviews[0].get("allowed_decisions") == ["respond"],
        "hitl_explicit_checkpoint": bool(
            snapshot.config["configurable"].get("checkpoint_id")
        ),
        "hitl_resume_structured": isinstance(
            resumed.get("structured_response"), Review
        ),
    }
    if negative_checks:
        output["temperature_parameter_error"] = error_type(
            lambda: make_model(include_temperature=True, max_tokens=24).invoke(
                "Reply with OK only."
            )
        )
        output["provider_json_schema_error"] = error_type(
            lambda: model.with_structured_output(
                Review, include_raw=True, method="json_schema"
            ).invoke(
                "Return title 测试, confidence 90, and nonblocking G1."
            )
        )
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--negative-checks", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            run_matrix(negative_checks=args.negative_checks),
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
