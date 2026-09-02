"""AI adapters for rubric dimension generation.

The platform keeps exactly one AI capability in M0: draft two-field scoring
criteria from a question's six material groups. Scene metadata, titles and
internal status never enter the generation contract. Business validation of
the drafts (actionability, privacy) is applied by the worker handler, not
here, so this module stays infrastructure-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class RubricGenerationFailure(RuntimeError):
    """Safe-to-display rubric generation failure with a stable machine code."""

    def __init__(self, code: str, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class MaterialExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_name: str | None = None
    content_text: str


class MaterialBadCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_text: str
    teacher_feedback_texts: list[str]
    reason_summary: str | None = None


class MaterialMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_label: str | None = None
    content_text: str


class RubricGenerationInput(BaseModel):
    """The six material groups; nothing outside them may influence generation."""

    model_config = ConfigDict(extra="forbid")

    task_prompt: str
    reference_examples: list[MaterialExample] = Field(default_factory=list)
    bad_cases: list[MaterialBadCase] = Field(default_factory=list)
    reference_answer: str
    memory_materials: list[MaterialMemory] = Field(default_factory=list)


class CriterionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion: str = Field(min_length=1, max_length=2_000)
    pass_score: int = Field(ge=0, le=10)


class RubricGenerationResult(BaseModel):
    """Structured output contract shared by fake and production adapters."""

    model_config = ConfigDict(extra="forbid")

    criteria: list[CriterionDraft] = Field(min_length=1, max_length=20)


class RubricGenerator(Protocol):
    def generate(self, materials: RubricGenerationInput) -> RubricGenerationResult: ...


class FakeRubricGenerator:
    """Deterministic generator for tests; material markers select failure paths."""

    FAIL_MARKER = "SIMULATE_RUBRIC_FAILURE"
    VAGUE_MARKER = "SIMULATE_VAGUE_OUTPUT"

    def generate(self, materials: RubricGenerationInput) -> RubricGenerationResult:
        combined = "\n".join(
            [materials.task_prompt, materials.reference_answer]
            + [item.content_text for item in materials.reference_examples]
            + [item.content_text for item in materials.memory_materials]
            + [item.content_text for item in materials.bad_cases]
        )
        if self.FAIL_MARKER in combined:
            raise RubricGenerationFailure("AI_CALL_FAILED", "模拟 AI 生成失败。")
        if self.VAGUE_MARKER in combined:
            return RubricGenerationResult(
                criteria=[CriterionDraft(criterion="准确性", pass_score=6)]
            )
        criteria = [
            CriterionDraft(
                criterion=(
                    "核心事实与数据必须与题目提供的参考材料一致，不得虚构；"
                    "引用内容与来源表述保持一致。"
                ),
                pass_score=7,
            ),
            CriterionDraft(
                criterion=(
                    "输出必须完整覆盖题目要求的全部要点；遗漏任一要点即不合格，"
                    "并以老师确认的标准答案为对照基准。"
                ),
                pass_score=6,
            ),
        ]
        if materials.bad_cases:
            criteria.append(
                CriterionDraft(
                    criterion=(
                        "不得重复 Bad case 中老师明确否定的问题；"
                        "出现与被否定结果相同的缺陷即不合格。"
                    ),
                    pass_score=7,
                )
            )
        return RubricGenerationResult(criteria=criteria)


class ModelRubricGenerator:
    """Production adapter: one structured-output call, no continuity required."""

    def __init__(self, model: Any = None) -> None:
        if model is None:
            from app.lib.ai_runtime.model import build_runtime_model

            model, _identity = build_runtime_model()
        self._model = model

    def generate(self, materials: RubricGenerationInput) -> RubricGenerationResult:
        structured = self._model.with_structured_output(
            RubricGenerationResult, method="function_calling"
        )
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _render_materials(materials)},
        ]
        try:
            raw = structured.invoke(messages)
        except Exception as exc:  # provider errors must not leak raw details
            raise RubricGenerationFailure(
                "AI_CALL_FAILED", f"评分维度生成调用失败：{type(exc).__name__}"
            ) from exc
        if raw is None:
            raise RubricGenerationFailure("AI_OUTPUT_EMPTY", "评分维度生成返回空结果。")
        if not isinstance(raw, RubricGenerationResult):
            raw = RubricGenerationResult.model_validate(raw)
        if not raw.criteria:
            raise RubricGenerationFailure("AI_OUTPUT_INVALID", "评分维度不能为空。")
        return raw


_SYSTEM_PROMPT = """你是评测平台的评分维度起草助手。
只根据题目自身的六类材料起草评分维度，每个维度包含：
- criterion：完整、可执行的评判标准，必须同时写明判断对象、合格表现和主要问题；
- pass_score：0 到 10 的整数及格分。
禁止输出“准确性”“创新性”等孤立标签；禁止引用场景名称、用例标题或任何材料之外的信息。
输出 2 到 6 个维度，覆盖材料中真正影响结果质量的关键方面。"""


def _render_materials(materials: RubricGenerationInput) -> str:
    lines = [f"【题目】\n{materials.task_prompt}", f"【标准答案】\n{materials.reference_answer}"]
    if materials.reference_examples:
        rendered = "\n---\n".join(
            f"来源：{item.source_name or '未命名'}\n{item.content_text}"
            for item in materials.reference_examples
        )
        lines.append(f"【参考样例】\n{rendered}")
    if materials.bad_cases:
        rendered = "\n---\n".join(
            "\n".join(
                [f"坏结果：{item.content_text}"]
                + [f"老师反馈：{feedback}" for feedback in item.teacher_feedback_texts]
                + ([f"原因整理：{item.reason_summary}"] if item.reason_summary else [])
            )
            for item in materials.bad_cases
        )
        lines.append(f"【Bad case 与老师反馈】\n{rendered}")
    if materials.memory_materials:
        rendered = "\n---\n".join(
            f"来源：{item.source_label or '未命名'}\n{item.content_text}"
            for item in materials.memory_materials
        )
        lines.append(f"【记忆材料】\n{rendered}")
    return "\n\n".join(lines)


@dataclass(frozen=True)
class RuntimeAdapters:
    rubric_generator: RubricGenerator


_adapters: RuntimeAdapters = RuntimeAdapters(rubric_generator=FakeRubricGenerator())


def get_adapters() -> RuntimeAdapters:
    return _adapters


def set_adapters(adapters: RuntimeAdapters) -> None:
    global _adapters
    _adapters = adapters


def reset_adapters() -> None:
    global _adapters
    _adapters = RuntimeAdapters(rubric_generator=FakeRubricGenerator())


def production_adapters(model: Any = None) -> RuntimeAdapters:
    return RuntimeAdapters(rubric_generator=ModelRubricGenerator(model=model))
