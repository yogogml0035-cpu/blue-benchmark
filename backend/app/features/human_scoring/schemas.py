"""Public HTTP contracts for external submissions and immutable human scores."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator

from app.features.case_builder.authoring_schemas import QuestionInput
from app.features.evaluation_sets.rubric_schemas import RubricCriterion


MAX_SUBMISSION_BYTES = 1 * 1024 * 1024


class SubmissionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    content_text: str = Field(min_length=1, max_length=MAX_SUBMISSION_BYTES)

    @field_validator("command_id")
    @classmethod
    def normalize_command_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be blank")
        return value

    @field_validator("content_text")
    @classmethod
    def require_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content_text must not be blank")
        return value


class ScoreItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(min_length=1, max_length=64)
    score: StrictInt = Field(ge=0, le=100)
    reason: str | None = Field(default=None, max_length=5_000)
    hard_fail_triggered: StrictBool | None = None

    @field_validator("criterion_id")
    @classmethod
    def normalize_criterion_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("criterion_id must not be blank")
        return value

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class ScoreCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    items: list[ScoreItemInput] = Field(min_length=1, max_length=100)
    overall_reason: str | None = Field(default=None, max_length=5_000)
    parent_score_id: str | None = Field(default=None, max_length=36)

    @field_validator("command_id")
    @classmethod
    def normalize_command_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("command_id must not be blank")
        return value

    @field_validator("overall_reason")
    @classmethod
    def normalize_overall_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("parent_score_id")
    @classmethod
    def normalize_parent_score_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class SubmissionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    question_revision_id: str
    source: Literal["paste", "file"]
    original_name: str | None = None
    media_type: str
    size_bytes: int = Field(ge=1, le=MAX_SUBMISSION_BYTES)
    sha256: str = Field(min_length=64, max_length=64)
    content_text: str
    submitted_at: datetime


class QuestionRevisionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    revision_number: int = Field(ge=1)
    title: str
    summary: str
    question_input: QuestionInput
    reference_answer_text: str
    criteria: list[RubricCriterion]
    pass_threshold: int = Field(ge=0, le=100)


class HumanScoreItemView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str
    score: int = Field(ge=0, le=100)
    reason: str | None = None
    hard_fail_triggered: bool | None = None
    critical_passed: bool


class HumanScoreView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    submission_id: str
    question_revision_id: str
    parent_score_id: str | None = None
    status: Literal["submitted"]
    items: list[HumanScoreItemView]
    overall_reason: str | None = None
    total_score: int = Field(ge=0, le=100)
    critical_passed: bool
    passed: bool
    submitted_at: datetime


class HumanSubmissionResponse(BaseModel):
    submission: SubmissionView
    question_revision: QuestionRevisionView
    scores: list[HumanScoreView] = Field(default_factory=list)


class HumanScoreResponse(BaseModel):
    score: HumanScoreView


class HumanScoreHistoryResponse(BaseModel):
    submission_id: str
    scores: list[HumanScoreView] = Field(default_factory=list)
