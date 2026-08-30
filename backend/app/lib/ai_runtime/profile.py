from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from app.lib.settings import settings


AI_PROFILE_VERSION = "m0-deep-agents-0.7.11-tool-strategy-v1"
GRAPH_SCHEMA_VERSION = "m0-cocreation-graph-v1"

READ_TOOLS = frozenset({"ls", "read_file", "glob", "grep"})
ASK_TOOL = "ask_teacher"
FORBIDDEN_TOOLS = frozenset({"task", "write_todos", "execute", "write_file", "edit_file", "delete"})


@dataclass(frozen=True, slots=True)
class AIProfile:
    version: str
    model_spec: str
    strategy: str
    streaming: bool
    store_enabled: bool
    memory_enabled: bool
    general_purpose_subagent_enabled: bool
    max_model_calls: int
    max_tool_calls: int
    model_retries: int


def get_ai_profile() -> AIProfile:
    return AIProfile(
        version=AI_PROFILE_VERSION,
        model_spec=settings.ai_model_spec,
        strategy="ToolStrategy",
        streaming=False,
        store_enabled=False,
        memory_enabled=False,
        general_purpose_subagent_enabled=False,
        max_model_calls=settings.ai_model_call_limit,
        max_tool_calls=settings.ai_tool_call_limit,
        model_retries=settings.ai_model_retries,
    )


_profile_lock = Lock()
_registered_model_keys: set[str] = set()


def initialize_ai_runtime(model_spec: str | None = None) -> AIProfile:
    """Register process-wide safety defaults once for one exact model key.

    The application profile version is deliberately not stored in this global
    registry. A request may select only an already-registered process profile;
    graph construction remains keyed by the immutable application profile.
    """

    profile = get_ai_profile()
    key = model_spec or profile.model_spec
    with _profile_lock:
        if key not in _registered_model_keys:
            from deepagents import GeneralPurposeSubagentProfile, HarnessProfile, register_harness_profile

            register_harness_profile(
                key,
                HarnessProfile(
                    excluded_tools=frozenset(FORBIDDEN_TOOLS),
                    general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
                ),
            )
            _registered_model_keys.add(key)
    return profile


def registered_model_keys() -> frozenset[str]:
    with _profile_lock:
        return frozenset(_registered_model_keys)


def assert_tool_surface(actual: set[str] | frozenset[str], allowed: set[str] | frozenset[str]) -> None:
    hidden = set(actual) & set(FORBIDDEN_TOOLS)
    unexpected = set(actual) - set(allowed)
    if hidden or unexpected:
        raise RuntimeError(
            f"AI tool surface is not fail-closed: hidden={sorted(hidden)}, unexpected={sorted(unexpected)}"
        )
