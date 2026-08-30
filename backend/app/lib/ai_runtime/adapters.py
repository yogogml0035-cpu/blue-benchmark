from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.features.case_builder.cocreation_schemas import (
    AgentEvidenceRef,
    BatchAnalysis,
    CoCreationAgentResult,
    CoCreationKind,
    CoCreationQuestion,
    CoverageReview,
    JudgmentPackageContent,
    LineRangeLocator,
    ScenarioContractContent,
    SkillAttemptProposal,
    TaskGroupProposal,
)
from app.lib.ai_runtime.checkpoint import FakeCheckpointStore
from app.lib.ai_runtime.context import AgentRunContext
from app.lib.ai_runtime.evidence import EvidenceDocument, ReadOnlyEvidenceBackend
from app.lib.ai_runtime.middleware import ModelToolSurfaceMiddleware
from app.lib.ai_runtime.profile import (
    ASK_TOOL,
    READ_TOOLS,
    get_ai_profile,
    initialize_ai_runtime,
)
from app.lib.settings import settings


class AskTeacherToolInput(BaseModel):
    question_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    gap_type: str = Field(min_length=1)
    evidence_refs: list[AgentEvidenceRef] = Field(default_factory=list)


def _ask_teacher(
    question_id: str,
    question: str,
    reason: str,
    gap_type: str,
    evidence_refs: list[AgentEvidenceRef] | None = None,
) -> str:
    """Pure marker tool; HumanInTheLoopMiddleware supplies the teacher response."""

    return "Teacher response is supplied through the respond decision."


from langchain_core.tools import tool as _langchain_tool

ask_teacher = _langchain_tool("ask_teacher")(_ask_teacher)


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    result: Any
    produced_checkpoint_id: str | None = None


class EvidenceAnalyzer(Protocol):
    def analyze(self, context: AgentRunContext, documents: dict[str, EvidenceDocument]) -> AgentRunResult: ...


class StandardCoCreator(Protocol):
    def start(self, context: AgentRunContext, kind: CoCreationKind) -> AgentRunResult: ...

    def resume(self, context: AgentRunContext, kind: CoCreationKind, checkpoint_id: str, answer: str) -> AgentRunResult: ...

    def reproject(self, context: AgentRunContext, kind: CoCreationKind, checkpoint_id: str) -> AgentRunResult: ...


class CoverageReviewer(Protocol):
    def review(self, context: AgentRunContext, snapshot: dict[str, Any]) -> AgentRunResult: ...


def _first_evidence_ref(context: AgentRunContext, documents: dict[str, EvidenceDocument]) -> AgentEvidenceRef:
    file_id = context.evidence_file_ids[0] if context.evidence_file_ids else next(iter(documents), "task-package")
    document = documents.get(file_id)
    line_count = 1
    if document and document.canonical_view:
        line_count = int(document.canonical_view.get("line_count") or 1)
    return AgentEvidenceRef(
        source_id=file_id,
        locator=LineRangeLocator(start_line=1, end_line=max(1, line_count)),
    )


class FakeEvidenceAnalyzer:
    """Deterministic adapter for CI and local development."""

    def analyze(self, context: AgentRunContext, documents: dict[str, EvidenceDocument]) -> AgentRunResult:
        scoped = [documents[file_id] for file_id in context.evidence_file_ids if file_id in documents and not documents[file_id].ignored]
        if not scoped:
            return AgentRunResult(BatchAnalysis(groups=[], unassigned_file_ids=list(context.evidence_file_ids), warnings=["没有可用于分组的资料。"], file_roles={}))
        file_ids = [item.file_id for item in scoped]
        attempts = [
            SkillAttemptProposal(
                attempt_key=f"attempt-{context.target_id[:32]}",
                label="上传批次中的一组真实执行证据",
                evidence_file_ids=file_ids,
                metadata={"source": "fake-adapter", "eof_required": True},
            )
        ]
        group = TaskGroupProposal(
            proposal_key=f"group-{context.target_id[:32]}-1",
            title="一组真实业务任务",
            summary="候选文件共同描述一个可复用的业务任务；老师仍需确认文件角色和边界。",
            evidence_file_ids=file_ids,
            attempts=attempts,
            evidence_refs=[_first_evidence_ref(context, documents)],
            warnings=[],
        )
        return AgentRunResult(
            BatchAnalysis(
                groups=[group],
                unassigned_file_ids=[],
                file_roles={item.file_id: (item.role if item.role != "unknown" else "runtime") for item in scoped},
                warnings=[],
            )
        )


class FakeStandardCoCreator:
    def __init__(self, checkpoint_store: FakeCheckpointStore | None = None) -> None:
        self.checkpoints = checkpoint_store or FakeCheckpointStore()

    @staticmethod
    def _question(context: AgentRunContext, kind: CoCreationKind, step: int, ref: AgentEvidenceRef) -> CoCreationQuestion:
        if step == 0:
            text = "这组真实任务共同要判断的最终交付结果是什么？"
            reason = "需要先确定所有题共享的任务边界，避免把不同目标混成一把尺子。"
            gap_type = "scope"
        else:
            text = "什么错误是无论如何都不能接受的，最低可用质量线是什么？"
            reason = "需要把老师的业务判断落成可复核的硬门禁和最低质量标准。"
            gap_type = "rule"
        return CoCreationQuestion(
            id=f"{kind.value}-question-{step + 1}",
            text=text,
            reason=reason,
            gap_type=gap_type,
            evidence_refs=[ref],
        )

    @staticmethod
    def _complete(context: AgentRunContext, kind: CoCreationKind, ref: AgentEvidenceRef) -> CoCreationAgentResult:
        if kind == CoCreationKind.scenario_contract:
            return CoCreationAgentResult(
                phase="complete",
                contract=ScenarioContractContent(
                    task_boundary="围绕已确认的真实业务任务形成可复用交付结果。",
                    input_contract=["只能使用老师确认可见的任务资料。"],
                    output_contract=["输出完整结果并可按来源回查关键判断。"],
                    hard_gates=["不得编造事实", "必须满足任务目标"],
                    quality_dimensions=["事实准确", "任务完成", "表达可用"],
                    prohibited_errors=["把未经确认的推测当成事实"],
                    capabilities=["从真实业务证据形成可复用标准"],
                    evidence_refs=[ref],
                ),
                delta={"added": ["场景任务边界"], "modified": ["共享硬门禁"], "deleted": [], "unresolved": []},
                evidence_refs=[ref],
            )
        return CoCreationAgentResult(
            phase="complete",
            judgment_package=JudgmentPackageContent(
                reference_results=["一份符合任务边界且可直接使用的老师确认结果。"],
                accepted_reasons=["覆盖任务目标", "关键事实可回查"],
                rejected_reasons=["编造事实", "遗漏必需交付内容"],
                hard_gates=["不得编造事实", "必须完成任务目标"],
                minimum_quality_line="老师可以直接使用或只需做极少量非实质修改。",
                task_specific_rules=["以老师确认的任务资料和表达偏好为准。"],
                capabilities=["按业务标准完成主观写作任务"],
                dimensions=["事实准确", "任务完成", "表达质量"],
                blocking_gaps=[],
                evidence_refs=[ref],
            ),
            delta={"added": ["判定依据包"], "modified": ["最低质量线"], "deleted": [], "unresolved": []},
            evidence_refs=[ref],
        )

    def start(self, context: AgentRunContext, kind: CoCreationKind) -> AgentRunResult:
        ref = AgentEvidenceRef(source_id=context.evidence_file_ids[0]) if context.evidence_file_ids else AgentEvidenceRef(source_id="task-package")
        result = CoCreationAgentResult(phase="question", question=self._question(context, kind, 0, ref), evidence_refs=[ref])
        checkpoint_id = self.checkpoints.put(context.thread_key, {"step": 0, "kind": kind.value, "result": result.model_dump(mode="json")})
        return AgentRunResult(result, checkpoint_id)

    def resume(self, context: AgentRunContext, kind: CoCreationKind, checkpoint_id: str, answer: str) -> AgentRunResult:
        state = self.checkpoints.get(checkpoint_id, context.thread_key)
        step = int(state.get("step", 0))
        ref = AgentEvidenceRef(source_id=context.evidence_file_ids[0]) if context.evidence_file_ids else AgentEvidenceRef(source_id="task-package")
        if step == 0:
            result = CoCreationAgentResult(
                phase="question",
                question=self._question(context, kind, 1, ref),
                delta={"added": ["老师已回答任务边界"], "modified": [], "deleted": [], "unresolved": []},
                evidence_refs=[ref],
            )
            next_step = 1
        else:
            result = self._complete(context, kind, ref)
            next_step = 2
        next_checkpoint = self.checkpoints.put(
            context.thread_key,
            {"step": next_step, "kind": kind.value, "last_answer": answer, "result": result.model_dump(mode="json")},
        )
        return AgentRunResult(result, next_checkpoint)

    def reproject(self, context: AgentRunContext, kind: CoCreationKind, checkpoint_id: str) -> AgentRunResult:
        state = self.checkpoints.get(checkpoint_id, context.thread_key)
        return AgentRunResult(CoCreationAgentResult.model_validate(state["result"]), checkpoint_id)


class FakeCoverageReviewer:
    def review(self, context: AgentRunContext, snapshot: dict[str, Any]) -> AgentRunResult:
        return AgentRunResult(
            CoverageReview(
                capabilities=list(snapshot.get("capabilities", [])),
                dimensions=list(snapshot.get("dimensions", [])),
                failure_modes=list(snapshot.get("failure_modes", [])),
                duplicate_groups=[],
                blank_areas=[],
                warnings=[],
                evidence_refs=[],
            )
        )


def _message_has_invalid_tool_calls(message: Any) -> bool:
    return bool(getattr(message, "invalid_tool_calls", None))


def _check_messages(result: dict[str, Any]) -> None:
    if any(_message_has_invalid_tool_calls(message) for message in result.get("messages", [])):
        raise RuntimeError("AI returned invalid_tool_calls")


def _checkpoint_id_from_state(state: Any) -> str | None:
    config = getattr(state, "config", None) or (state.get("config") if isinstance(state, dict) else None) or {}
    return (config.get("configurable") or {}).get("checkpoint_id")


def _interrupt_value(result: dict[str, Any]) -> Any | None:
    interrupts = result.get("__interrupt__") or result.get("interrupts")
    if not interrupts:
        return None
    item = interrupts[0] if isinstance(interrupts, (list, tuple)) else interrupts
    return getattr(item, "value", item)


def _question_from_interrupt(value: Any) -> CoCreationQuestion:
    if not isinstance(value, dict):
        raise RuntimeError("unexpected HITL interrupt envelope")
    action_requests = value.get("action_requests")
    review_configs = value.get("review_configs")
    if not isinstance(action_requests, list) or len(action_requests) != 1:
        raise RuntimeError("co-creator must produce exactly one ask_teacher action")
    action = action_requests[0]
    if not isinstance(action, dict) or action.get("name") != ASK_TOOL:
        raise RuntimeError("unexpected co-creator action")
    if not isinstance(review_configs, list) or len(review_configs) != 1:
        raise RuntimeError("co-creator must produce exactly one review config")
    allowed = review_configs[0].get("allowed_decisions") if isinstance(review_configs[0], dict) else None
    if allowed != ["respond"]:
        raise RuntimeError("only respond is allowed for ask_teacher")
    args = action.get("args")
    if not isinstance(args, dict):
        raise RuntimeError("ask_teacher args are invalid")
    args = {**args, "evidence_refs": args.get("evidence_refs") or [], "id": args.get("id") or args.get("question_id")}
    return CoCreationQuestion.model_validate(args)


class _DeepAgentBase:
    def __init__(self, checkpointer: Any = None) -> None:
        self.checkpointer = checkpointer
        self.profile = initialize_ai_runtime()

    @staticmethod
    def _model() -> Any:
        if settings.ai_base_url:
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(model_name=settings.ai_model_id, base_url=settings.ai_base_url, streaming=False)
        return settings.ai_model_spec

    @staticmethod
    def _permissions(file_ids: tuple[str, ...] | list[str]) -> list[Any]:
        from deepagents.middleware.filesystem import FilesystemPermission

        paths = [path for file_id in file_ids for path in (f"/evidence/{file_id}", f"/evidence/{file_id}/**")]
        return [
            FilesystemPermission(operations=["read"], paths=paths, mode="allow"),
            FilesystemPermission(operations=["read"], paths=["/**"], mode="deny"),
            FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
        ]

    def _graph(
        self,
        context: AgentRunContext,
        documents: dict[str, EvidenceDocument],
        schema: Any,
        *,
        allowed_tools: set[str],
        ask_teacher: bool = False,
    ) -> Any:
        from deepagents import create_deep_agent
        from deepagents.middleware.filesystem import FilesystemMiddleware
        from langchain.agents.middleware import ModelCallLimitMiddleware, ModelRetryMiddleware, ToolCallLimitMiddleware
        from langchain.agents.structured_output import ToolStrategy

        if "_permissions" not in inspect.signature(FilesystemMiddleware).parameters:
            raise RuntimeError("deepagents FilesystemMiddleware permission signature changed")
        backend = ReadOnlyEvidenceBackend(documents)
        fs = FilesystemMiddleware(
            backend=backend,
            tools=["ls", "read_file", "glob", "grep"],
            _permissions=self._permissions(list(documents)),
        )
        middleware: list[Any] = [
            fs,
            ModelToolSurfaceMiddleware(allowed_tools),
            ModelCallLimitMiddleware(run_limit=self.profile.max_model_calls, exit_behavior="error"),
            ToolCallLimitMiddleware(run_limit=self.profile.max_tool_calls, exit_behavior="error"),
            ModelRetryMiddleware(max_retries=self.profile.model_retries, on_failure="error"),
        ]
        interrupt_on = {ASK_TOOL: {"allowed_decisions": ["respond"]}} if ask_teacher else None
        extra_tools = [globals()["ask_teacher"]] if ask_teacher else []
        graph = create_deep_agent(
            model=self._model(),
            tools=extra_tools,
            system_prompt=(
                "Read the evidence manifest first. For every long file use explicit offset and limit, "
                "continue until EOF, and cite only canonical evidence locators. "
                "Produce one highest-value teacher question at a time."
            ),
            middleware=middleware,
            subagents=[],
            skills=[],
            memory=[],
            backend=backend,
            permissions=self._permissions(list(documents)),
            interrupt_on=interrupt_on,
            response_format=ToolStrategy(schema),
            context_schema=AgentRunContext,
            checkpointer=self.checkpointer,
            store=None,
            name=context.target_type,
        )
        return graph

    def _invoke(self, graph: Any, payload: dict[str, Any], context: AgentRunContext, checkpoint_id: str | None = None) -> AgentRunResult:
        config = {"configurable": {"thread_id": context.thread_key}}
        if checkpoint_id:
            config["configurable"]["checkpoint_id"] = checkpoint_id
        result = graph.invoke(payload, config=config)
        _check_messages(result)
        state = graph.get_state(config)
        interrupt = _interrupt_value(result)
        if interrupt is not None:
            question = _question_from_interrupt(interrupt)
            return AgentRunResult(CoCreationAgentResult(phase="question", question=question), _checkpoint_id_from_state(state))
        structured = result.get("structured_response")
        if structured is None:
            raise RuntimeError("Deep Agent did not return structured_response")
        return AgentRunResult(CoCreationAgentResult.model_validate(structured), _checkpoint_id_from_state(state))


class DeepAgentsEvidenceAnalyzer(_DeepAgentBase):
    def analyze(self, context: AgentRunContext, documents: dict[str, EvidenceDocument]) -> AgentRunResult:
        from app.features.case_builder.cocreation_schemas import BatchAnalysis

        graph = self._graph(context, documents, BatchAnalysis, allowed_tools=set(READ_TOOLS) | {"BatchAnalysis"})
        return self._invoke(graph, {"messages": [{"role": "user", "content": "Analyze this task package and propose task groups."}]}, context)


class DeepAgentsStandardCoCreator(_DeepAgentBase):
    def start(self, context: AgentRunContext, kind: CoCreationKind) -> AgentRunResult:
        if self.checkpointer is None:
            raise RuntimeError("standard_cocreator requires a checkpointer")
        schema = CoCreationAgentResult
        documents = documents_for_files(list(context.evidence_file_ids))
        graph = self._graph(context, documents, schema, allowed_tools=set(READ_TOOLS) | {ASK_TOOL, "CoCreationAgentResult"}, ask_teacher=True)
        return self._invoke(graph, {"messages": [{"role": "user", "content": f"Start {kind.value} co-creation."}]}, context)

    def resume(self, context: AgentRunContext, kind: CoCreationKind, checkpoint_id: str, answer: str) -> AgentRunResult:
        from langgraph.types import Command

        if self.checkpointer is None:
            raise RuntimeError("standard_cocreator requires a checkpointer")
        graph = self._graph(context, documents_for_files(list(context.evidence_file_ids)), CoCreationAgentResult, allowed_tools=set(READ_TOOLS) | {ASK_TOOL, "CoCreationAgentResult"}, ask_teacher=True)
        return self._invoke(graph, Command(resume={"decisions": [{"type": "respond", "response": answer}]}), context, checkpoint_id)

    def reproject(self, context: AgentRunContext, kind: CoCreationKind, checkpoint_id: str) -> AgentRunResult:
        if self.checkpointer is None:
            raise RuntimeError("standard_cocreator requires a checkpointer")
        graph = self._graph(context, documents_for_files(list(context.evidence_file_ids)), CoCreationAgentResult, allowed_tools=set(READ_TOOLS) | {ASK_TOOL, "CoCreationAgentResult"}, ask_teacher=True)
        config = {"configurable": {"thread_id": context.thread_key, "checkpoint_id": checkpoint_id}}
        state = graph.get_state(config)
        interrupt = _interrupt_value(state.values if hasattr(state, "values") else state)
        if interrupt is not None:
            return AgentRunResult(CoCreationAgentResult(phase="question", question=_question_from_interrupt(interrupt)), checkpoint_id)
        structured = (state.values if hasattr(state, "values") else state).get("structured_response")
        if structured is None:
            raise RuntimeError("accepted checkpoint has no projectable structured response")
        return AgentRunResult(CoCreationAgentResult.model_validate(structured), checkpoint_id)


class DeepAgentsCoverageReviewer(_DeepAgentBase):
    def review(self, context: AgentRunContext, snapshot: dict[str, Any]) -> AgentRunResult:
        graph = self._graph(context, {}, CoverageReview, allowed_tools={"CoverageReview"})
        return self._invoke(graph, {"messages": [{"role": "user", "content": json.dumps(snapshot, ensure_ascii=False)}]}, context)


@dataclass(frozen=True, slots=True)
class RuntimeAdapters:
    evidence_analyzer: EvidenceAnalyzer
    standard_cocreator: StandardCoCreator
    coverage_reviewer: CoverageReviewer


_fake_checkpoints = FakeCheckpointStore()
_adapters: RuntimeAdapters = RuntimeAdapters(
    evidence_analyzer=FakeEvidenceAnalyzer(),
    standard_cocreator=FakeStandardCoCreator(_fake_checkpoints),
    coverage_reviewer=FakeCoverageReviewer(),
)


def production_adapters(checkpointer: Any) -> RuntimeAdapters:
    return RuntimeAdapters(
        evidence_analyzer=DeepAgentsEvidenceAnalyzer(),
        standard_cocreator=DeepAgentsStandardCoCreator(checkpointer),
        coverage_reviewer=DeepAgentsCoverageReviewer(),
    )


def get_adapters() -> RuntimeAdapters:
    return _adapters


def set_adapters(adapters: RuntimeAdapters) -> None:
    global _adapters
    _adapters = adapters


def reset_adapters() -> None:
    global _adapters
    _adapters = RuntimeAdapters(
        evidence_analyzer=FakeEvidenceAnalyzer(),
        standard_cocreator=FakeStandardCoCreator(_fake_checkpoints),
        coverage_reviewer=FakeCoverageReviewer(),
    )
