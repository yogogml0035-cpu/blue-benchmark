"""Pydantic contracts for the unified question library and six material groups."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.features.question_library import rubric_rules
from app.lib.errors import AppError


class QuestionStatus(StrEnum):
    generating = "generating"
    pending_review = "pending_review"
    generation_failed = "generation_failed"
    published = "published"


class NextAction(StrEnum):
    wait_for_generation = "wait_for_generation"
    retry_generation = "retry_generation"
    review_and_publish = "review_and_publish"
    published = "published"


NEXT_ACTION_BY_STATUS = {
    QuestionStatus.generating: NextAction.wait_for_generation,
    QuestionStatus.generation_failed: NextAction.retry_generation,
    QuestionStatus.pending_review: NextAction.review_and_publish,
    QuestionStatus.published: NextAction.published,
}


# ---------------------------------------------------------------------------
# Six material groups
# ---------------------------------------------------------------------------


class ReferenceExampleIn(BaseModel):
    """Teacher-provided content the local Agent actually read, then distilled."""

    model_config = ConfigDict(extra="forbid")

    client_ref_id: str = Field(min_length=1, max_length=128)
    source_name: str | None = Field(default=None, max_length=200)
    content_text: str = Field(min_length=1, max_length=200_000)

    @field_validator("content_text")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("参考样例正文不能为空白。")
        return stripped


class MemoryMaterialIn(BaseModel):
    """Raw memory fragment the local Agent loaded this round and deemed relevant."""

    model_config = ConfigDict(extra="forbid")

    client_ref_id: str = Field(min_length=1, max_length=128)
    source_label: str | None = Field(default=None, max_length=200)
    content_text: str = Field(min_length=1, max_length=200_000)

    @field_validator("content_text")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("记忆材料正文不能为空白。")
        return stripped


class BadCaseIn(BaseModel):
    """A rejected real result with the teacher feedback bound to it."""

    model_config = ConfigDict(extra="forbid")

    content_text: str = Field(min_length=1, max_length=200_000)
    teacher_feedback_texts: list[str] = Field(min_length=1, max_length=20)
    reason_summary: str | None = Field(default=None, max_length=5_000)

    @field_validator("content_text", "reason_summary")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("Bad case 正文与原因整理不能为空白。")
        return stripped

    @field_validator("teacher_feedback_texts")
    @classmethod
    def _feedback_not_blank(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("老师反馈原话不能为空白。")
        return cleaned


class CaseIn(BaseModel):
    """One evaluation question payload inside a batch upload command."""

    model_config = ConfigDict(extra="forbid")

    client_case_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    task_prompt: str = Field(min_length=1, max_length=100_000)
    reference_examples: list[ReferenceExampleIn] = Field(default_factory=list, max_length=50)
    bad_cases: list[BadCaseIn] = Field(default_factory=list, max_length=50)
    reference_answer: str = Field(min_length=1, max_length=200_000)
    memory_materials: list[MemoryMaterialIn] = Field(default_factory=list, max_length=50)

    @field_validator("title", "task_prompt", "reference_answer")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("标题、题目与标准答案不能为空白。")
        return stripped

    @model_validator(mode="after")
    def _check_ids(self) -> "CaseIn":
        for field_name in ("reference_examples", "memory_materials"):
            ids = [item.client_ref_id for item in getattr(self, field_name)]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{field_name} 内部 client_ref_id 必须唯一。")
        return self


class BatchUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    command_id: str = Field(min_length=1, max_length=255)
    cases: list[CaseIn] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _check_case_ids(self) -> "BatchUploadRequest":
        ids = [item.client_case_id for item in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("cases 内部 client_case_id 必须唯一。")
        return self


# ---------------------------------------------------------------------------
# Two-field rubric criteria
# ---------------------------------------------------------------------------

CRITERION_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


def assert_public_material_text(value: str, *, field_label: str) -> None:
    """Server-side backstop against obvious secrets, paths and internal content."""

    try:
        rubric_rules.validate_public_text(value, field_label=field_label)
    except ValueError as exc:
        raise AppError(422, "PRIVATE_CONTENT_REJECTED", str(exc)) from exc


def assert_actionable_criterion(criterion: str) -> None:
    """Reject vague one-word labels that cannot guide stable scoring."""

    try:
        rubric_rules.validate_criterion_text(criterion)
    except ValueError as exc:
        raise AppError(422, "CRITERION_TOO_VAGUE", str(exc)) from exc


class CriterionIn(BaseModel):
    """Administrator-supplied criterion; identical shape to the AI output contract."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    criterion: str = Field(min_length=rubric_rules.MIN_CRITERION_LENGTH, max_length=2_000)
    pass_score: int = Field(ge=0, le=10)

    @field_validator("criterion")
    @classmethod
    def _validate_criterion(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("评分标准不能为空白。")
        rubric_rules.validate_criterion_text(stripped)
        return stripped


class CriteriaPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    content_revision: int = Field(ge=1)
    criteria: list[CriterionIn] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _check_ids(self) -> "CriteriaPatchRequest":
        ids = [item.id for item in self.criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("评分维度 id 必须唯一。")
        return self


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

class ReferenceExampleView(BaseModel):
    client_ref_id: str
    source_name: str | None
    content_text: str


class MemoryMaterialView(BaseModel):
    client_ref_id: str
    source_label: str | None
    content_text: str


class BadCaseView(BaseModel):
    content_text: str
    teacher_feedback_texts: list[str]
    reason_summary: str | None


class CriterionView(BaseModel):
    id: str
    criterion: str
    pass_score: int


class GenerationErrorView(BaseModel):
    code: str
    message: str


class QuestionListItem(BaseModel):
    id: str
    scene_id: str
    scene_name: str
    client_case_id: str
    title: str
    status: QuestionStatus
    rubric_criterion_count: int | None
    next_action: NextAction
    created_at: str
    updated_at: str
    published_at: str | None


class QuestionLibraryResponse(BaseModel):
    items: list[QuestionListItem]
    total: int


class QuestionDetailResponse(BaseModel):
    id: str
    scene_id: str
    scene_name: str
    client_case_id: str
    title: str
    task_prompt: str
    reference_examples: list[ReferenceExampleView]
    bad_cases: list[BadCaseView]
    reference_answer: str
    memory_materials: list[MemoryMaterialView]
    criteria: list[CriterionView] | None
    status: QuestionStatus
    next_action: NextAction
    content_revision: int
    active_operation_id: str | None
    last_error: GenerationErrorView | None
    created_at: str
    updated_at: str
    published_at: str | None


class CaseReceipt(BaseModel):
    client_case_id: str
    question_id: str
    status: QuestionStatus


class BatchUploadResponse(BaseModel):
    command_id: str
    scene_id: str
    accepted_case_count: int
    cases: list[CaseReceipt]


class QuestionSaveRegenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    content_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    task_prompt: str | None = Field(default=None, min_length=1, max_length=100_000)
    reference_examples: list[ReferenceExampleIn] | None = Field(default=None, max_length=50)
    bad_cases: list[BadCaseIn] | None = Field(default=None, max_length=50)
    reference_answer: str | None = Field(default=None, min_length=1, max_length=200_000)
    memory_materials: list[MemoryMaterialIn] | None = Field(default=None, max_length=50)


class QuestionTitleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    content_revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)


class QuestionCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    content_revision: int = Field(ge=1)


class OperationAcceptedResponse(BaseModel):
    question_id: str
    status: QuestionStatus
    operation_id: str | None


def canonical_payload_hash(payload: BaseModel) -> str:
    # NFC-normalize so semantically identical payloads from different client
    # stacks (macOS decomposition, different JSON encoders) hash identically.
    raw = json.dumps(
        payload.model_dump(mode="json"),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    normalized = unicodedata.normalize("NFC", raw)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def assert_case_materials_private(case: CaseIn) -> None:
    """Backstop scan across every text field of one uploaded case."""

    assert_public_material_text(case.title, field_label="用例标题")
    assert_public_material_text(case.client_case_id, field_label="client_case_id")
    assert_public_material_text(case.task_prompt, field_label="题目正文")
    assert_public_material_text(case.reference_answer, field_label="标准答案")
    for item in case.reference_examples:
        assert_public_material_text(item.content_text, field_label="参考样例")
        if item.source_name:
            assert_public_material_text(item.source_name, field_label="参考样例来源")
    for item in case.memory_materials:
        assert_public_material_text(item.content_text, field_label="记忆材料")
        if item.source_label:
            assert_public_material_text(item.source_label, field_label="记忆材料来源")
    for item in case.bad_cases:
        assert_public_material_text(item.content_text, field_label="Bad case")
        for feedback in item.teacher_feedback_texts:
            assert_public_material_text(feedback, field_label="老师反馈")
        if item.reason_summary:
            assert_public_material_text(item.reason_summary, field_label="原因整理")

