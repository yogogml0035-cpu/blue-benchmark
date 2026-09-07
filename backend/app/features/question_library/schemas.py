"""Pydantic contracts for the scene-scoped question library and six material groups."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.features.question_library import rubric_rules
from app.lib.errors import AppError


class QuestionStatus(StrEnum):
    generating = "generating"
    pending_review = "pending_review"
    generation_failed = "generation_failed"
    published = "published"
    # Deletion accepted: the question is frozen (no edits, generation,
    # publish, resume or event replay) until cross-store cleanup finishes
    # and the row is removed in the final business transaction.
    deleting = "deleting"


class NextAction(StrEnum):
    wait_for_generation = "wait_for_generation"
    retry_generation = "retry_generation"
    review_criteria = "review_criteria"
    publish = "publish"
    published = "published"
    wait_for_deletion = "wait_for_deletion"


NEXT_ACTION_BY_STATUS = {
    QuestionStatus.generating: NextAction.wait_for_generation,
    QuestionStatus.generation_failed: NextAction.retry_generation,
    QuestionStatus.published: NextAction.published,
    QuestionStatus.deleting: NextAction.wait_for_deletion,
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
    teacher_feedback_texts: list[Annotated[str, Field(min_length=1, max_length=5_000)]] = Field(
        min_length=1, max_length=20
    )
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
# Complete rubric criteria contract
# ---------------------------------------------------------------------------

CRITERION_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


def assert_public_material_text(value: str, *, field_label: str) -> None:
    """Server-side backstop against obvious secrets, paths and internal content."""

    try:
        rubric_rules.validate_public_text(value, field_label=field_label)
    except ValueError as exc:
        raise AppError(422, "PRIVATE_CONTENT_REJECTED", str(exc)) from exc


class SourceCitationIn(BaseModel):
    """Teacher-visible citation into this question's materials."""

    model_config = ConfigDict(extra="forbid")

    locator: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=500)


class BasisClaimIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=1, max_length=1_000)
    kind: Literal["teacher_explicit", "ai_inferred"]
    citation: SourceCitationIn | None = None

    @model_validator(mode="after")
    def _explicit_requires_citation(self) -> "BasisClaimIn":
        if self.kind == "teacher_explicit" and self.citation is None:
            raise ValueError("老师明确要求必须附带可核查的材料引用。")
        return self


class CriterionBasisIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    explanation: str = Field(min_length=1, max_length=2_000)
    claims: list[BasisClaimIn] = Field(min_length=1, max_length=8)


class PassScoreBasisIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    explained_score: int = Field(ge=0, le=10)
    explanation: str = Field(min_length=1, max_length=2_000)
    claims: list[BasisClaimIn] = Field(min_length=1, max_length=8)


class ScoreAnchorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=0, le=10)
    description: str = Field(min_length=1, max_length=1_000)


class CriterionIn(BaseModel):
    """Administrator-supplied criterion; identical shape to the AI output contract.

    Teacher-edit semantics (deliberately weaker than the GENERATION contract):
    ``pass_score`` accepts ANY integer 0-10 — anchors are explanatory, never a
    whitelist; ``score_anchors`` may be empty or omit ``pass_score``; the two
    bases may be ``None`` for manually created criteria (explicitly empty
    auxiliary content, not a missing-field fallback). Editing the score does
    NOT rewrite or auto-fill anchors/bases; the UI flags a stale
    ``explained_score`` for the teacher to review.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    criterion: str = Field(min_length=rubric_rules.MIN_CRITERION_LENGTH, max_length=2_000)
    pass_score: int = Field(ge=0, le=10)
    score_anchors: list[ScoreAnchorIn] = Field(default_factory=list, max_length=6)
    criterion_basis: CriterionBasisIn | None = None
    pass_score_basis: PassScoreBasisIn | None = None

    @field_validator("criterion")
    @classmethod
    def _validate_criterion(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("评分标准不能为空白。")
        rubric_rules.validate_criterion_text(stripped)
        return stripped

    @field_validator("score_anchors")
    @classmethod
    def _anchors_unique_sorted(cls, value: list[ScoreAnchorIn]) -> list[ScoreAnchorIn]:
        scores = [a.score for a in value]
        if len(scores) != len(set(scores)):
            raise ValueError("分数锚点必须唯一。")
        return sorted(value, key=lambda a: a.score)


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


class SourceCitationView(BaseModel):
    locator: str
    quote: str


class BasisClaimView(BaseModel):
    claim: str
    kind: Literal["teacher_explicit", "ai_inferred"]
    citation: SourceCitationView | None


class CriterionBasisView(BaseModel):
    explanation: str
    claims: list[BasisClaimView]


class PassScoreBasisView(BaseModel):
    explained_score: int
    explanation: str
    claims: list[BasisClaimView]


class ScoreAnchorView(BaseModel):
    score: int
    description: str


class CriterionView(BaseModel):
    id: str
    criterion: str
    pass_score: int
    score_anchors: list[ScoreAnchorView]
    criterion_basis: CriterionBasisView | None
    pass_score_basis: PassScoreBasisView | None


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
    criteria_confirmed: bool
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
    criteria_confirmed: bool
    # Soft reminder flag: at least one stored citation no longer matches the
    # current materials (autosave decoupled materials from regeneration).
    criteria_basis_stale: bool
    status: QuestionStatus
    next_action: NextAction
    content_revision: int
    active_operation_id: str | None
    last_operation_id: str | None
    last_error: GenerationErrorView | None
    deletion: "DeleteStateView | None"
    delete_confirmation_required: bool
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


class QuestionMaterialsPatchRequest(BaseModel):
    """Partial material autosave; absent fields keep their current values.

    Writes text only: never bumps ``content_revision``, never touches
    criteria, never enqueues generation. Lists are replaced wholesale when
    provided (item shapes reuse the batch-intake models, so validation and
    ``client_ref_id`` uniqueness come for free).
    """

    model_config = ConfigDict(extra="forbid")

    content_revision: int = Field(ge=1)
    task_prompt: str | None = Field(default=None, min_length=1, max_length=100_000)
    reference_answer: str | None = Field(default=None, min_length=1, max_length=200_000)
    reference_examples: list[ReferenceExampleIn] | None = Field(default=None, max_length=50)
    bad_cases: list[BadCaseIn] | None = Field(default=None, max_length=50)
    memory_materials: list[MemoryMaterialIn] | None = Field(default=None, max_length=50)


class CriterionPatchRequest(BaseModel):
    """Field-level criterion autosave; absent fields keep their values.

    Selection flags, confirmation state and the unselected candidate pool are
    never touched here; the supplied fields are re-validated through the same
    ``CriterionIn`` contract the explicit criteria save uses. Stored basis
    citations are NOT re-validated against materials on this path — staleness
    surfaces as the soft ``criteria_basis_stale`` reminder instead.
    """

    model_config = ConfigDict(extra="forbid")

    content_revision: int = Field(ge=1)
    criterion: str | None = Field(default=None, min_length=1, max_length=2_000)
    pass_score: int | None = Field(default=None, ge=0, le=10)
    score_anchors: list[ScoreAnchorIn] | None = Field(default=None, max_length=6)


class QuestionTitleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    content_revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)


class QuestionCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    content_revision: int = Field(ge=1)


class QuestionDeleteRequest(BaseModel):
    """Protected delete-acceptance contract.

    ``confirmation_title`` is only required for questions that were ever
    published; it must match the current title exactly (after Unicode NFC
    normalization and trimming) or the delete is rejected. Acceptance starts
    a durable cleanup operation; success is only reported after every
    cross-store trace of the question is gone.
    """

    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    content_revision: int = Field(ge=1)
    confirmation_title: str | None = Field(default=None, max_length=200)


class DeleteStateView(BaseModel):
    """Projection of the accepted deletion operation (no material content)."""

    operation_id: str
    phase: Literal["queued", "running", "succeeded", "failed"]
    error: GenerationErrorView | None = None


class DeleteAcceptedResponse(BaseModel):
    question_id: str
    status: QuestionStatus
    operation_id: str


RunEventKind = Literal[
    "run_started",
    "run_resumed",
    "stage",
    "message_delta",
    "message",
    "tool_started",
    "tool_finished",
    "tool_failed",
    "interrupted",
    "run_completed",
    "run_failed",
]


class RunEventView(BaseModel):
    """One persisted public progress event of a generation operation."""

    sequence: int
    kind: RunEventKind
    stage: str | None = None
    text: str | None = None
    tool: str | None = None
    detail: str | None = None
    attempt: int
    created_at: str


class RunEventsResponse(BaseModel):
    question_id: str
    operation_id: str | None
    status: QuestionStatus
    events: list[RunEventView]
    last_sequence: int


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
