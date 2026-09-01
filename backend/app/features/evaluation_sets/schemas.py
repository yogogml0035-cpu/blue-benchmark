from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

class DraftStatus(StrEnum):
    active = "active"
    discarded = "discarded"


class MemberStatus(StrEnum):
    included = "included"
    removed = "removed"


class ImpactReviewStatus(StrEnum):
    not_required = "not_required"
    review_required = "review_required"
    reviewed = "reviewed"
    no_conflict_confirmed = "no_conflict_confirmed"


class EvaluationVersionStatus(StrEnum):
    frozen = "frozen"


class DraftCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)


class DraftDiscardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    draft_revision: int = Field(ge=0)


class MemberMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    draft_revision: int = Field(ge=0)
    task_package_id: str = Field(min_length=1, max_length=36)
    task_package_revision: int = Field(ge=0)
    action: Literal["include", "remove"]


class QuestionRevisionMemberMutationRequest(BaseModel):
    """Add or remove one immutable published authoring revision."""

    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    draft_revision: int = Field(ge=0)
    question_revision_id: str = Field(min_length=1, max_length=36)
    question_revision_number: int = Field(ge=1)
    question_revision_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")
    action: Literal["include", "remove"]


class ImpactReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    draft_revision: int = Field(ge=0)
    decision: Literal["reviewed", "confirm_no_conflict"]
    note: str | None = Field(default=None, max_length=5_000)


class BatchImpactReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    draft_revision: int = Field(ge=0)
    note: str | None = Field(default=None, max_length=5_000)


class CoverageReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    draft_revision: int = Field(ge=0)


class CoverageConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    draft_revision: int = Field(ge=0)
    confirmed: bool
    note: str | None = Field(default=None, max_length=5_000)

    @model_validator(mode="after")
    def require_note_for_risk_acceptance(self) -> "CoverageConfirmationRequest":
        if self.confirmed and not (self.note or "").strip():
            raise ValueError("coverage risk confirmation requires a note")
        return self


class FreezeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    draft_revision: int = Field(ge=0)
    coverage_risk_confirmed: bool = False
    risk_confirmation_note: str | None = Field(default=None, max_length=5_000)

    @model_validator(mode="after")
    def require_risk_note(self) -> "FreezeRequest":
        if self.coverage_risk_confirmed and not (self.risk_confirmation_note or "").strip():
            raise ValueError("coverage risk confirmation requires a note")
        return self


class DraftMemberView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    task_package_id: str | None = None
    question_revision_id: str | None = None
    task_package_revision: int = Field(ge=0)
    question_revision_number: int | None = Field(default=None, ge=1)
    question_revision_hash: str | None = Field(default=None, min_length=64, max_length=64)
    status: MemberStatus
    review_status: ImpactReviewStatus
    deterministic_conflicts: list[str] = Field(default_factory=list)
    ai_suggestions: list[str] = Field(default_factory=list)
    teacher_note: str | None = None
    sort_order: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_source(self) -> "DraftMemberView":
        if (self.task_package_id is None) == (self.question_revision_id is None):
            raise ValueError("a draft member must reference exactly one source")
        if self.question_revision_id is not None and (
            self.question_revision_number is None or self.question_revision_hash is None
        ):
            raise ValueError("an authored member must include its revision identity")
        if self.task_package_id is not None and (
            self.question_revision_number is not None or self.question_revision_hash is not None
        ):
            raise ValueError("a legacy member cannot include authored revision fields")
        return self


class CoverageSnapshotView(BaseModel):
    id: str
    draft_revision: int = Field(ge=0)
    capabilities: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    failure_modes: list[str] = Field(default_factory=list)
    duplicate_groups: list[str] = Field(default_factory=list)
    blank_areas: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    risk_confirmed: bool = False
    risk_confirmation_note: str | None = None
    confirmed_at: datetime | None = None


class ActiveOperationView(BaseModel):
    id: str
    kind: Literal["coverage_review", "freeze_package"]
    status: Literal["queued", "running", "failed", "projection_pending"]


class WorkingSetDraftView(BaseModel):
    id: str
    workspace_id: str
    revision: int = Field(ge=0)
    status: DraftStatus
    base_version_id: str | None = None
    contract_revision: int = Field(ge=1)
    members: list[DraftMemberView] = Field(default_factory=list)
    coverage: CoverageSnapshotView | None = None
    blocking_issues: list[str] = Field(default_factory=list)
    next_action: Literal[
        "add_or_remove_tasks",
        "review_contract_impact",
        "run_coverage_review",
        "confirm_coverage_risk",
        "freeze",
        "wait_for_processing",
        "retry_processing",
        "none",
    ]
    active_operation: ActiveOperationView | None = None
    created_at: datetime
    updated_at: datetime


class WorkingSetDraftResponse(BaseModel):
    draft: WorkingSetDraftView


class VersionSummary(BaseModel):
    id: str
    workspace_id: str
    version_number: int = Field(ge=1)
    status: EvaluationVersionStatus
    overall_sha256: str = Field(min_length=64, max_length=64)
    frozen_at: datetime


class VersionListResponse(BaseModel):
    workspace_id: str
    versions: list[VersionSummary]


class PublishedQuestionRevisionSummary(BaseModel):
    id: str
    question_draft_id: str
    revision: int = Field(ge=1)
    title: str
    pass_threshold: int = Field(ge=0, le=100)
    content_sha256: str = Field(min_length=64, max_length=64)
    published_at: datetime


class PublishedQuestionRevisionListResponse(BaseModel):
    workspace_id: str
    revisions: list[PublishedQuestionRevisionSummary] = Field(default_factory=list)


class ManifestResponse(BaseModel):
    version: VersionSummary
    manifest: dict[str, Any]


class FreezeAcceptedResponse(BaseModel):
    draft: WorkingSetDraftView
    operation_id: str
