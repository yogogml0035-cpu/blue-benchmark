from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.messages import ToolMessage


def _tool_name(tool: Any) -> str:
    if isinstance(tool, dict):
        return str(tool.get("name", ""))
    return str(getattr(tool, "name", ""))


class ModelToolSurfaceMiddleware(AgentMiddleware):
    """Hide and reject tools outside one named Agent's allowlist."""

    def __init__(self, allowed_tool_names: set[str] | frozenset[str]) -> None:
        super().__init__()
        self.allowed_tool_names = frozenset(allowed_tool_names)
        self.tools = []

    def _visible(self, tools: list[Any]) -> list[Any]:
        return [tool for tool in tools if _tool_name(tool) in self.allowed_tool_names]

    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]):
        return handler(request.override(tools=self._visible(request.tools)))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ):
        return await handler(request.override(tools=self._visible(request.tools)))

    @staticmethod
    def _reject(request: ToolCallRequest) -> ToolMessage:
        call_id = str(request.tool_call.get("id", "unknown"))
        name = str(request.tool_call.get("name", "unknown"))
        return ToolMessage(
            content=f"Tool '{name}' is not allowed for this Agent.",
            tool_call_id=call_id,
            status="error",
        )

    def wrap_tool_call(self, request: ToolCallRequest, handler):
        if str(request.tool_call.get("name", "")) not in self.allowed_tool_names:
            return self._reject(request)
        return handler(request)

    async def awrap_tool_call(self, request: ToolCallRequest, handler):
        if str(request.tool_call.get("name", "")) not in self.allowed_tool_names:
            return self._reject(request)
        return await handler(request)
