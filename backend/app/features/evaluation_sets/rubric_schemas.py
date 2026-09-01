"""Public contracts for rubric co-creation and immutable question publication."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.features.case_builder.authoring_schemas import AuthoringQuestion, QuestionInput


class RubricDraftStatus(StrEnum):
    not_started = "not_started"
    queued = "queued"
    processing = "processing"
    waiting_for_teacher = "waiting_for_teacher"
    review_ready = "review_ready"
    confirmed = "confirmed"
    published = "published"
    stale = "stale"
    failed = "failed"
    projection_pending = "projection_pending"


class CriticalMode(StrEnum):
    none = "none"
    minimum = "minimum"
    hard_fail = "hard_fail"


class RubricCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=2_000)
    max_score: int = Field(ge=1, le=100)
    award_points: list[str] = Field(min_length=1, max_length=50)
    deduction_points: list[str] = Field(default_factory=list, max_length=50)
    critical: bool = False
    critical_mode: CriticalMode = CriticalMode.none
    critical_min_score: int | None = Field(default=None, ge=0, le=100)
    hard_fail_conditions: list[str] = Field(default_factory=list, max_length=20)
    reference_expected_score: int = Field(ge=0, le=100)
    reference_score_reason: str = Field(min_length=1, max_length=2_000)
    reference_hard_fail_triggered: bool = False

    @model_validator(mode="after")
    def validate_critical_rule(self) -> "RubricCriterion":
        for field_name in (
            "name",
            "purpose",
            "reference_score_reason",
        ):
            value = getattr(self, field_name).strip()
            if not value:
                raise ValueError(f"{field_name} must not be blank")
            setattr(self, field_name, value)
        self.award_points = [item.strip() for item in self.award_points if item.strip()]
        self.deduction_points = [item.strip() for item in self.deduction_points if item.strip()]
        self.hard_fail_conditions = [item.strip() for item in self.hard_fail_conditions if item.strip()]
        if not self.award_points:
            raise ValueError("criteria require at least one award point")
        if self.reference_expected_score > self.max_score:
            raise ValueError("reference_expected_score cannot exceed max_score")
        if not self.critical:
            if self.critical_mode != CriticalMode.none or self.critical_min_score is not None or self.hard_fail_conditions:
                raise ValueError("non-critical criteria cannot define a critical rule")
            if self.reference_hard_fail_triggered:
                raise ValueError("non-critical criteria cannot trigger a hard fail")
            return self
        if self.critical_mode == CriticalMode.none:
            raise ValueError("critical criteria require minimum or hard_fail mode")
        if self.critical_mode == CriticalMode.minimum:
            if self.critical_min_score is None or self.critical_min_score > self.max_score:
                raise ValueError("minimum critical score must be within max_score")
            if self.hard_fail_conditions or self.reference_hard_fail_triggered:
                raise ValueError("minimum criteria cannot define hard-fail conditions")
        if self.critical_mode == CriticalMode.hard_fail:
            if self.critical_min_score is not None or not self.hard_fail_conditions:
                raise ValueError("hard_fail criteria require conditions and no minimum score")
        return self


_SIMILARITY_SCORING_TERMS = (
    "相似度",
    "字面相似",
    "措辞一致",
    "复刻标准答案",
    "标题一致",
    "段落顺序一致",
    "结构相似",
    "similarity",
    "lexical match",
)

_PUBLIC_CJK = re.compile(r"[\u3400-\u9fff]")
_PUBLIC_HOST_PATH = re.compile(
    r"(?:^|[\s(])/(?:Users|home|private|tmp|var|etc|workspace|evidence)(?:/|$)|[A-Za-z]:[\\/]"
)
_PUBLIC_FORBIDDEN_TERMS = (
    "private_reasoning",
    "system_prompt",
    "thread_id",
    "checkpoint",
    "storage_key",
    "api_key",
    "api key",
    "access token",
    "raw_token",
    "secret",
    "credential",
    "password",
    "tool_args",
    "tool_result",
    "parsed_text",
    "raw_output",
    "reasoning",
    "private",
    "凭证",
    "系统提示",
    "私有推理",
    "绝对路径",
)


class RubricContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criteria: list[RubricCriterion] = Field(min_length=1, max_length=100)
    pass_threshold: int = Field(default=60, ge=0, le=100)

    @model_validator(mode="after")
    def validate_content(self) -> "RubricContent":
        ids = [item.id for item in self.criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("rubric criterion IDs must be unique")
        if sum(item.max_score for item in self.criteria) != 100:
            raise ValueError("rubric max scores must sum to exactly 100")
        scored_text = [
            text
            for item in self.criteria
            for text in [
                item.name,
                item.purpose,
                *item.award_points,
                *item.deduction_points,
                *item.hard_fail_conditions,
                item.reference_score_reason,
            ]
        ]
        if any(any(term.casefold() in text.casefold() for term in _SIMILARITY_SCORING_TERMS) for text in scored_text):
            raise ValueError("rubric must not use reference-answer similarity as a scoring criterion")
        return self


def public_text_error(value: str) -> str | None:
    folded = value.casefold()
    if not _PUBLIC_CJK.search(value):
        return "not_chinese"
    if (
        any(term in folded for term in _PUBLIC_FORBIDDEN_TERMS)
        or value.startswith(("/", "\\"))
        or "file://" in folded
        or _PUBLIC_HOST_PATH.search(value)
    ):
        return "not_safe"
    return None


def validate_public_rubric_text(rubric: RubricContent) -> None:
    for criterion in rubric.criteria:
        for value in (
            criterion.name,
            criterion.purpose,
            *criterion.award_points,
            *criterion.deduction_points,
            *criterion.hard_fail_conditions,
            criterion.reference_score_reason,
        ):
            error = public_text_error(value)
            if error is not None:
                raise ValueError(error)


class RubricOperationView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["rubric_process", "rubric_reproject"]
    status: Literal["queued", "running", "failed", "projection_pending"]


class RubricDraftView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    question_draft_id: str
    question_title: str
    source_question_revision: int = Field(ge=0)
    status: RubricDraftStatus
    revision: int = Field(ge=0)
    question_input: QuestionInput
    reference_answer_text: str
    rubric: RubricContent | None = None
    reference_total_score: int | None = Field(default=None, ge=0, le=100)
    reference_critical_passed: bool | None = None
    reference_passed: bool | None = None
    pending_question: AuthoringQuestion | None = None
    blocking_issues: list[str] = Field(default_factory=list)
    next_action: Literal[
        "start_rubric",
        "wait_for_processing",
        "review_rubric",
        "confirm_rubric",
        "publish",
        "retry_processing",
        "stale_upstream",
        "none",
    ]
    active_operation: RubricOperationView | None = None
    published_revision_id: str | None = None
    confirmed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RubricDraftResponse(BaseModel):
    rubric: RubricDraftView


class RubricGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    question_revision: int = Field(ge=0)


class RubricPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    rubric_revision: int = Field(ge=0)
    rubric: RubricContent


class RubricConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    rubric_revision: int = Field(ge=0)


class RubricPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    rubric_revision: int = Field(ge=0)


class RubricRevisionSummary(BaseModel):
    id: str
    question_draft_id: str
    revision: int = Field(ge=1)
    source_question_revision: int = Field(ge=0)
    pass_threshold: int = Field(ge=0, le=100)
    content_sha256: str = Field(min_length=64, max_length=64)
    published_at: datetime


class RubricRevisionListResponse(BaseModel):
    question_draft_id: str
    revisions: list[RubricRevisionSummary] = Field(default_factory=list)


class RubricDeriveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
