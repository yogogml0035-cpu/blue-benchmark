"""Public contracts for the user-visible benchmark authoring conversation."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AuthoringConversationStatus(StrEnum):
    queued = "queued"
    processing = "processing"
    waiting_for_teacher = "waiting_for_teacher"
    review_ready = "review_ready"
    ready = "ready"
    confirmed = "confirmed"
    failed = "failed"
    projection_pending = "projection_pending"
    continuity_reset = "continuity_reset"


class AuthoringMessageRole(StrEnum):
    teacher = "teacher"
    assistant = "assistant"


class AuthoringMessageType(StrEnum):
    chat = "chat"
    standard_answer = "standard_answer"


class QuestionDraftStatus(StrEnum):
    candidate = "candidate"
    input_answer_drafting = "input_answer_drafting"
    input_answer_review = "input_answer_review"
    input_answer_confirmed = "input_answer_confirmed"
    discarded = "discarded"


class QuestionMaterialRole(StrEnum):
    unconfirmed = "unconfirmed"
    brief = "brief"
    fact = "fact"
    style = "style"
    current_draft = "current_draft"
    background = "background"
    ignored = "ignored"


class AuthoringEventKind(StrEnum):
    phase_started = "phase_started"
    phase_completed = "phase_completed"
    action_summary = "action_summary"
    public_message_ready = "public_message_ready"
    snapshot_changed = "snapshot_changed"
    waiting_for_teacher = "waiting_for_teacher"
    failed = "failed"
    completed = "completed"


class AuthoringNextAction(StrEnum):
    wait_for_processing = "wait_for_processing"
    confirm_question_boundaries = "confirm_question_boundaries"
    provide_standard_answer = "provide_standard_answer"
    review_question = "review_question"
    confirm_input_answer = "confirm_input_answer"
    retry_processing = "retry_processing"
    continuity_reset = "continuity_reset"
    none = "none"


class QuestionMaterialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: str = Field(min_length=1, max_length=255)
    role: QuestionMaterialRole = QuestionMaterialRole.unconfirmed
    priority: int = Field(default=0, ge=0, le=100)
    rationale: str | None = Field(default=None, max_length=2_000)

    @field_validator("file_id")
    @classmethod
    def normalize_file_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("file_id must not be blank")
        return value


class QuestionMaterialView(QuestionMaterialInput):
    file_name: str | None = None


class QuestionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_instruction: str = Field(min_length=1, max_length=10_000)
    materials: list[QuestionMaterialInput] = Field(default_factory=list, max_length=100)
    must_include: list[str] = Field(default_factory=list, max_length=100)
    prohibited: list[str] = Field(default_factory=list, max_length=100)
    background: str | None = Field(default=None, max_length=10_000)

    @model_validator(mode="after")
    def normalize_text(self) -> "QuestionInput":
        if not self.task_instruction.strip():
            raise ValueError("task_instruction must not be blank")
        self.must_include = [item.strip() for item in self.must_include if item.strip()]
        self.prohibited = [item.strip() for item in self.prohibited if item.strip()]
        if self.background is not None:
            self.background = self.background.strip() or None
        file_ids = [item.file_id for item in self.materials]
        if len(file_ids) != len(set(file_ids)):
            raise ValueError("question materials must reference unique files")
        return self


class BadSample(BaseModel):
    """A teacher-confirmed bad result from a real Agent execution."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    source_ref: str = Field(min_length=1, max_length=500)
    content_text: str = Field(min_length=1, max_length=50_000)
    teacher_feedback_texts: list[str] = Field(min_length=1, max_length=20)
    reason_summary: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def validate_public_evidence(self) -> "BadSample":
        values = [self.source_ref, self.content_text, self.reason_summary, *self.teacher_feedback_texts]
        forbidden = (
            "system_prompt", "private_reasoning", "tool_result", "tool_args", "thread_id",
            "checkpoint", "storage_key", "api_key", "access token", "password", "绝对路径",
            "系统提示", "私有推理", "工具调用", "存储键", "凭证",
        )
        for value in values:
            folded = value.casefold()
            if (
                not value.strip()
                or value.startswith(("/", "\\"))
                or "file://" in folded
                or any(marker in folded for marker in ("/users/", "/home/", "/private/", "c:\\"))
            ):
                raise ValueError("bad sample contains an invalid public text value")
            if any(term in value.casefold() for term in forbidden):
                raise ValueError("bad sample contains private or internal trace text")
        if any(not item.strip() for item in self.teacher_feedback_texts):
            raise ValueError("teacher_feedback_texts must not be blank")
        self.reason_summary = self.reason_summary.strip()
        return self


class AuthoringQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1, max_length=5_000)
    reason: str = Field(min_length=1, max_length=2_000)
    gap_type: Literal["scope", "input", "standard_answer", "evidence"]
    question_draft_id: str | None = Field(default=None, max_length=36)


class AuthoringConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=200)
    upload_batch_id: str | None = Field(default=None, max_length=36)
    task_instruction: str | None = Field(default=None, max_length=10_000)
    message: str | None = Field(default=None, max_length=20_000)
    reference_answer_text: str | None = Field(default=None, max_length=50_000)
    source_file_ids: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def normalize_input(self) -> "AuthoringConversationCreateRequest":
        self.command_id = self.command_id.strip()
        if not self.command_id:
            raise ValueError("command_id must not be blank")
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("title must not be blank")
        for field_name in ("task_instruction", "message", "reference_answer_text"):
            value = getattr(self, field_name)
            if value is not None:
                setattr(self, field_name, value if value.strip() else None)
        self.source_file_ids = [item.strip() for item in self.source_file_ids]
        if any(not item for item in self.source_file_ids):
            raise ValueError("source_file_ids must not contain blanks")
        if len(self.source_file_ids) != len(set(self.source_file_ids)):
            raise ValueError("source_file_ids must be unique")
        if not (self.upload_batch_id or self.task_instruction or self.message):
            raise ValueError("an upload batch, task instruction, or message is required")
        return self


class AuthoringMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    conversation_revision: int = Field(ge=0)
    content: str = Field(min_length=1, max_length=50_000)
    message_type: AuthoringMessageType = AuthoringMessageType.chat
    question_draft_id: str | None = Field(default=None, max_length=36)
    attachment_ids: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("command_id")
    @classmethod
    def normalize_command_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("command_id must not be blank")
        return value

    @model_validator(mode="after")
    def normalize_input(self) -> "AuthoringMessageRequest":
        self.command_id = self.command_id.strip()
        self.content = self.content.strip()
        if not self.content:
            raise ValueError("content must not be blank")
        self.attachment_ids = [item.strip() for item in self.attachment_ids]
        if any(not item for item in self.attachment_ids):
            raise ValueError("attachment_ids must not contain blanks")
        if len(self.attachment_ids) != len(set(self.attachment_ids)):
            raise ValueError("attachment_ids must be unique")
        return self


class QuestionBoundaryGroupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="老师确认的一个独立任务。", max_length=2_000)
    evidence_file_ids: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def normalize_input(self) -> "QuestionBoundaryGroupInput":
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("title must not be blank")
        self.summary = self.summary.strip() or "老师确认的一个独立任务。"
        self.evidence_file_ids = [item.strip() for item in self.evidence_file_ids]
        if any(not item for item in self.evidence_file_ids):
            raise ValueError("evidence_file_ids must not contain blanks")
        if len(self.evidence_file_ids) != len(set(self.evidence_file_ids)):
            raise ValueError("evidence_file_ids must be unique")
        return self


class QuestionBoundaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    conversation_revision: int = Field(ge=0)
    action: Literal["confirm", "split", "merge", "discard"]
    draft_ids: list[str] = Field(default_factory=list, min_length=1, max_length=100)
    groups: list[QuestionBoundaryGroupInput] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_action(self) -> "QuestionBoundaryRequest":
        self.command_id = self.command_id.strip()
        if not self.command_id:
            raise ValueError("command_id must not be blank")
        self.draft_ids = [item.strip() for item in self.draft_ids]
        if any(not item for item in self.draft_ids):
            raise ValueError("draft_ids must not contain blanks")
        if len(self.draft_ids) != len(set(self.draft_ids)):
            raise ValueError("draft_ids must be unique")
        if self.action == "split" and len(self.groups) < 2:
            raise ValueError("split requires at least two groups")
        if self.action == "split" and len(self.draft_ids) != 1:
            raise ValueError("split requires exactly one draft")
        if self.action == "merge" and len(self.draft_ids) < 2:
            raise ValueError("merge requires at least two drafts")
        if self.action != "split" and self.groups:
            raise ValueError("groups are only allowed for split")
        return self


class InputAnswerPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    draft_revision: int = Field(ge=0)
    input: QuestionInput
    reference_answer_text: str | None = Field(default=None, max_length=50_000)
    bad_samples: list[BadSample] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def normalize_input(self) -> "InputAnswerPatchRequest":
        self.command_id = self.command_id.strip()
        if not self.command_id:
            raise ValueError("command_id must not be blank")
        if self.reference_answer_text is not None:
            self.reference_answer_text = self.reference_answer_text if self.reference_answer_text.strip() else None
        sample_ids = [item.id for item in self.bad_samples]
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("bad sample IDs must be unique")
        return self


class InputAnswerConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    draft_revision: int = Field(ge=0)

    @field_validator("command_id")
    @classmethod
    def normalize_command_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("command_id must not be blank")
        return value


class QuestionLifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    draft_revision: int = Field(ge=0)
    action: Literal["derive", "disable", "restore", "delete"]

    @field_validator("command_id")
    @classmethod
    def normalize_command_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("command_id must not be blank")
        return value


class AuthoringRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    conversation_revision: int = Field(ge=0)

    @field_validator("command_id")
    @classmethod
    def normalize_command_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("command_id must not be blank")
        return value


class AuthoringContinuityResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=2_000)

    @field_validator("command_id", "reason")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value


class AuthoringOperationView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["authoring_process", "authoring_reproject"]
    status: Literal["queued", "running", "failed", "projection_pending"]


class AuthoringMessageView(BaseModel):
    id: str
    sequence: int = Field(ge=1)
    role: AuthoringMessageRole
    message_type: AuthoringMessageType
    content: str
    attachment_ids: list[str] = Field(default_factory=list)
    question_draft_id: str | None = None
    created_at: datetime


class BenchmarkQuestionDraftView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    conversation_id: str
    title: str
    summary: str
    status: QuestionDraftStatus
    revision: int = Field(ge=0)
    input: QuestionInput
    bad_samples: list[BadSample] = Field(default_factory=list)
    reference_answer_text: str | None = None
    reference_answer_source: Literal["teacher_message", "teacher_input"] | None = None
    evidence_file_ids: list[str] = Field(default_factory=list)
    materials: list[QuestionMaterialView] = Field(default_factory=list)
    confirmed_revision: int | None = Field(default=None, ge=0)
    confirmed_at: datetime | None = None
    lifecycle_status: Literal["draft", "active", "disabled", "deleted"] = "draft"
    active_revision_id: str | None = None
    current_revision_number: int | None = Field(default=None, ge=1)


class AuthoringConversationView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    upload_batch_id: str | None = None
    source_file_count: int = Field(default=0, ge=0)
    title: str
    status: AuthoringConversationStatus
    revision: int = Field(ge=0)
    messages: list[AuthoringMessageView] = Field(default_factory=list)
    question_drafts: list[BenchmarkQuestionDraftView] = Field(default_factory=list)
    pending_question: AuthoringQuestion | None = None
    next_action: AuthoringNextAction
    active_operation: AuthoringOperationView | None = None
    events_cursor: int = Field(default=0, ge=0)
    blocking_issues: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class AuthoringConversationResponse(BaseModel):
    conversation: AuthoringConversationView


class QuestionListResponse(BaseModel):
    workspace_id: str
    questions: list[BenchmarkQuestionDraftView] = Field(default_factory=list)


class AuthoringEventView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    kind: AuthoringEventKind
    payload: dict[str, object]
    created_at: datetime


class AuthoringEventListResponse(BaseModel):
    conversation_id: str
    events: list[AuthoringEventView] = Field(default_factory=list)
    next_cursor: int = Field(ge=0)
