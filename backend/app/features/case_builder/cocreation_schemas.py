from __future__ import annotations

from datetime import datetime
from enum import StrEnum
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TaskPackageStatus(StrEnum):
    proposed = "proposed"
    confirmed = "confirmed"
    replaced = "replaced"


class CoCreationKind(StrEnum):
    scenario_contract = "scenario_contract"
    task_judgment = "task_judgment"


class CoCreationStatus(StrEnum):
    queued = "queued"
    processing = "processing"
    waiting_for_teacher = "waiting_for_teacher"
    ready_for_confirmation = "ready_for_confirmation"
    confirmed = "confirmed"
    failed = "failed"
    projection_pending = "projection_pending"
    continuity_reset = "continuity_reset"


class ContractRevisionStatus(StrEnum):
    draft = "draft"
    confirmed = "confirmed"
    superseded = "superseded"


class LineRangeLocator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["line_range"] = "line_range"
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_order(self) -> "LineRangeLocator":
        if self.end_line < self.start_line:
            raise ValueError("end_line must not precede start_line")
        return self


class JsonPointerLocator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["json_pointer"] = "json_pointer"
    pointer: str = Field(min_length=1, max_length=2_000)


class EventLocator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["event_id"] = "event_id"
    event_id: str = Field(min_length=1, max_length=255)


EvidenceLocator = Annotated[
    LineRangeLocator | JsonPointerLocator | EventLocator,
    Field(discriminator="kind"),
]


class AgentEvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=255)
    locator: EvidenceLocator | None = None
    quote: str | None = Field(default=None, max_length=2_000)


class SkillAttemptProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_key: str = Field(min_length=1, max_length=255)
    label: str = Field(min_length=1, max_length=500)
    evidence_file_ids: list[str] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def metadata_must_be_safe(cls, value: dict[str, Any]) -> dict[str, Any]:
        forbidden = ("secret", "token", "password", "credential", "private_reasoning", "authorization", "api_key")
        def contains_forbidden_key(item: Any) -> bool:
            if isinstance(item, dict):
                return any(
                    any(term in str(key).casefold() for term in forbidden) or contains_forbidden_key(child)
                    for key, child in item.items()
                )
            if isinstance(item, list):
                return any(contains_forbidden_key(child) for child in item)
            return False

        if contains_forbidden_key(value):
            raise ValueError("attempt metadata cannot contain credentials or private reasoning")
        if len(json.dumps(value, ensure_ascii=False, default=str)) > 4_000:
            raise ValueError("attempt metadata is too large")
        return value

    @model_validator(mode="after")
    def unique_files(self) -> "SkillAttemptProposal":
        if len(self.evidence_file_ids) != len(set(self.evidence_file_ids)):
            raise ValueError("attempt evidence_file_ids must be unique")
        return self


class TaskGroupProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_key: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2_000)
    evidence_file_ids: list[str] = Field(min_length=1)
    attempts: list[SkillAttemptProposal] = Field(default_factory=list)
    evidence_refs: list[AgentEvidenceRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_group(self) -> "TaskGroupProposal":
        if len(self.evidence_file_ids) != len(set(self.evidence_file_ids)):
            raise ValueError("group evidence_file_ids must be unique")
        if len(self.attempts) != len({attempt.attempt_key for attempt in self.attempts}):
            raise ValueError("group attempts must be unique")
        referenced = set(self.evidence_file_ids)
        if any(set(attempt.evidence_file_ids) - referenced for attempt in self.attempts):
            raise ValueError("attempt files must belong to the group")
        return self


class BatchAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    groups: list[TaskGroupProposal] = Field(default_factory=list, max_length=100)
    unassigned_file_ids: list[str] = Field(default_factory=list)
    file_roles: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_file_ownership(self) -> "BatchAnalysis":
        if len(self.groups) != len({group.proposal_key for group in self.groups}):
            raise ValueError("group proposal keys must be unique")
        all_ids: list[str] = []
        for group in self.groups:
            all_ids.extend(group.evidence_file_ids)
        all_ids.extend(self.unassigned_file_ids)
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("a file may belong to only one proposed group")
        return self


class SkillAttemptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_key: str = Field(min_length=1, max_length=255)
    label: str = Field(min_length=1, max_length=500)
    evidence_file_ids: list[str] = Field(min_length=1)


class TaskGroupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_key: str | None = Field(default=None, max_length=255)
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="老师确认的真实任务分组。", max_length=2_000)
    evidence_file_ids: list[str] = Field(min_length=1)
    attempts: list[SkillAttemptInput] = Field(default_factory=list)
    initialization_only: bool = False

    @model_validator(mode="after")
    def validate_group(self) -> "TaskGroupInput":
        if len(self.evidence_file_ids) != len(set(self.evidence_file_ids)):
            raise ValueError("group evidence_file_ids must be unique")
        if len(self.attempts) != len({attempt.attempt_key for attempt in self.attempts}):
            raise ValueError("group attempts must be unique")
        referenced = set(self.evidence_file_ids)
        if any(set(attempt.evidence_file_ids) - referenced for attempt in self.attempts):
            raise ValueError("attempt files must belong to the group")
        return self


class SkillAttemptView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_key: str
    label: str
    evidence_file_ids: list[str]


class GroupingConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    batch_revision: int = Field(ge=0)
    groups: list[TaskGroupInput] = Field(default_factory=list, max_length=100)


class TaskPackageSummary(BaseModel):
    id: str
    workspace_id: str
    upload_batch_id: str
    status: TaskPackageStatus
    title: str
    evidence_file_ids: list[str]
    attempts: list[SkillAttemptView] = Field(default_factory=list)
    revision: int = Field(ge=0)
    initialization_only: bool = False
    has_contract: bool = False
    has_judgment_package: bool = False
    created_at: datetime
    updated_at: datetime


class TaskPackageResponse(BaseModel):
    task_package: TaskPackageSummary


class TaskPackageListResponse(BaseModel):
    batch_id: str
    batch_revision: int = Field(ge=0)
    task_packages: list[TaskPackageSummary]


class TaskPackageWorkspaceListResponse(BaseModel):
    workspace_id: str
    task_packages: list[TaskPackageSummary]


class BlockingGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1, max_length=2_000)
    blocking: bool = True
    evidence_refs: list[AgentEvidenceRef] = Field(default_factory=list)


class ScenarioContractContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_boundary: str = Field(min_length=1, max_length=5_000)
    input_contract: list[str] = Field(min_length=1, max_length=50)
    output_contract: list[str] = Field(min_length=1, max_length=50)
    hard_gates: list[str] = Field(min_length=1, max_length=50)
    quality_dimensions: list[str] = Field(min_length=1, max_length=50)
    prohibited_errors: list[str] = Field(default_factory=list, max_length=50)
    capabilities: list[str] = Field(min_length=1, max_length=50)
    evidence_refs: list[AgentEvidenceRef] = Field(min_length=1)


class JudgmentPackageContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_results: list[str] = Field(min_length=1, max_length=20)
    accepted_reasons: list[str] = Field(min_length=1, max_length=50)
    rejected_reasons: list[str] = Field(min_length=1, max_length=50)
    hard_gates: list[str] = Field(min_length=1, max_length=50)
    minimum_quality_line: str = Field(min_length=1, max_length=5_000)
    task_specific_rules: list[str] = Field(min_length=1, max_length=50)
    capabilities: list[str] = Field(min_length=1, max_length=50)
    dimensions: list[str] = Field(min_length=1, max_length=50)
    blocking_gaps: list[BlockingGap] = Field(default_factory=list, max_length=50)
    evidence_refs: list[AgentEvidenceRef] = Field(min_length=1)


class CoCreationDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    added: list[str] = Field(default_factory=list, max_length=100)
    modified: list[str] = Field(default_factory=list, max_length=100)
    deleted: list[str] = Field(default_factory=list, max_length=100)
    unresolved: list[BlockingGap] = Field(default_factory=list, max_length=100)


class CoCreationQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1, max_length=5_000)
    reason: str = Field(min_length=1, max_length=2_000)
    gap_type: Literal["fact", "judgment", "rule", "scope", "evidence"]
    evidence_refs: list[AgentEvidenceRef] = Field(default_factory=list)


class CoCreationAgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase: Literal["question", "complete"]
    question: CoCreationQuestion | None = None
    delta: CoCreationDelta = Field(default_factory=CoCreationDelta)
    contract: ScenarioContractContent | None = None
    judgment_package: JudgmentPackageContent | None = None
    blocking_gaps: list[BlockingGap] = Field(default_factory=list, max_length=100)
    evidence_refs: list[AgentEvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_phase(self) -> "CoCreationAgentResult":
        if self.phase == "question" and self.question is None:
            raise ValueError("question phase must contain exactly one question")
        if self.phase == "complete" and self.question is not None:
            raise ValueError("complete phase must not contain a question")
        return self


class CoverageReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capabilities: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    failure_modes: list[str] = Field(default_factory=list)
    duplicate_groups: list[str] = Field(default_factory=list)
    blank_areas: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evidence_refs: list[AgentEvidenceRef] = Field(default_factory=list)


class EvaluationFileSnapshot(BaseModel):
    """Internal cross-feature snapshot; storage_key never enters an HTTP DTO."""

    model_config = ConfigDict(extra="forbid")

    file_id: str
    name: str
    media_type: str
    size_bytes: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64)
    parse_state: str
    role: str
    required: bool
    ignored: bool
    visibility: str
    storage_key: str


class EvaluationTaskSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_package_id: str
    workspace_id: str
    title: str
    task_description: str | None = None
    revision: int = Field(ge=0)
    contract_revision_id: str
    contract: ScenarioContractContent
    draft: dict[str, Any]
    judgment_package: JudgmentPackageContent
    files: list[EvaluationFileSnapshot] = Field(min_length=1)
    attempts: list[SkillAttemptProposal] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


class CoCreationStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    kind: CoCreationKind = CoCreationKind.scenario_contract
    task_package_revision: int = Field(default=0, ge=0)
    initialization_only: bool = False


class CoCreationAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    question_id: str = Field(min_length=1, max_length=255)
    answer: str = Field(min_length=1, max_length=10_000)
    business_revision: int = Field(ge=0)

    @model_validator(mode="after")
    def trim(self) -> "CoCreationAnswerRequest":
        self.answer = self.answer.strip()
        if not self.answer:
            raise ValueError("answer must not be blank")
        return self


class CoCreationConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_revision: int = Field(ge=0)
    command_id: str = Field(min_length=1, max_length=255)


class CoCreationRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    business_revision: int = Field(ge=0)


class CoCreationResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=2_000)


class CoCreationTurnView(BaseModel):
    id: str
    turn_revision: int = Field(ge=1)
    question: CoCreationQuestion | None = None
    answer: str | None = None
    delta: CoCreationDelta | None = None
    status: str
    created_at: datetime
    answered_at: datetime | None = None


class CoCreationSessionView(BaseModel):
    id: str
    workspace_id: str
    task_package_id: str
    kind: CoCreationKind
    purpose: str | None = None
    initialization_only: bool = False
    status: CoCreationStatus
    business_revision: int = Field(ge=0)
    pending_question: CoCreationQuestion | None = None
    contract: ScenarioContractContent | None = None
    judgment_package: JudgmentPackageContent | None = None
    turns: list[CoCreationTurnView] = Field(default_factory=list)
    next_action: Literal[
        "wait_for_processing",
        "answer_question",
        "review_and_confirm",
        "retry_processing",
        "continuity_reset",
        "none",
    ]
    active_operation_id: str | None = None
    blocking_issues: list[str] = Field(default_factory=list)


class CoCreationSessionResponse(BaseModel):
    session: CoCreationSessionView


class PromotionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1, max_length=5_000)


class PromotionDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
