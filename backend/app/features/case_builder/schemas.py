from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CaseState(str, Enum):
    parsing = "parsing"
    parse_failed = "parse_failed"
    ready_for_ai = "ready_for_ai"
    generating = "generating"
    waiting_for_input = "waiting_for_input"
    waiting_for_confirmation = "waiting_for_confirmation"
    ai_failed = "ai_failed"
    confirmed = "confirmed"


class EvidenceRef(BaseModel):
    kind: Literal["attachment_excerpt", "task_description", "teacher_answer"]
    source_id: str = Field(min_length=1)
    locator: str | None = None
    quote: str | None = None


class Scenario(BaseModel):
    summary: str = Field(min_length=1)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class ReferenceOutcome(BaseModel):
    accepted_result: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class Fact(BaseModel):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class TeacherJudgment(BaseModel):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class ProposedStandard(BaseModel):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class Unknown(BaseModel):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    blocking: bool = False


class Dimension(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: Literal["hard_gate", "required_quality", "diagnostic"]
    criterion: str = Field(min_length=1)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class DraftContent(BaseModel):
    scenario: Scenario
    task_goal: str = Field(min_length=1)
    input_summary: str = Field(min_length=1)
    output_requirements: list[str] = Field(min_length=1)
    prohibited_errors: list[str] = Field(default_factory=list)
    reference_outcome: ReferenceOutcome | None = None
    facts: list[Fact] = Field(default_factory=list)
    teacher_judgments: list[TeacherJudgment] = Field(default_factory=list)
    proposed_standards: list[ProposedStandard] = Field(default_factory=list)
    unknowns: list[Unknown] = Field(default_factory=list)
    primary_capability: str = Field(min_length=1)
    dimensions: list[Dimension] = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)


class PendingQuestion(BaseModel):
    id: str
    text: str
    reason: str


class LastError(BaseModel):
    stage: Literal["parse", "ai"]
    code: str
    message: str
    retryable: bool


class Attachment(BaseModel):
    id: str
    original_name: str
    media_type: str
    size_bytes: int = Field(ge=0)


class CandidateCase(BaseModel):
    id: str
    source_case_id: str
    draft_revision: int = Field(ge=1)
    content: DraftContent
    confirmed_by: str
    confirmed_at: datetime


class BuilderSnapshot(BaseModel):
    draft_revision: int = Field(ge=0)
    pending_question: PendingQuestion | None = None
    draft: DraftContent | None = None
    last_error: LastError | None = None


class Case(BaseModel):
    id: str
    workspace_id: str
    title: str
    task_description: str | None
    state: CaseState
    attachment: Attachment
    builder: BuilderSnapshot
    candidate_case: CandidateCase | None = None
    created_at: datetime
    updated_at: datetime


class CaseDetail(BaseModel):
    case: Case


class AnswerRequest(BaseModel):
    question_id: str = Field(min_length=1)
    answer: str = Field(min_length=1, max_length=10_000)

    @field_validator("answer", mode="before")
    @classmethod
    def trim_answer(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class ConfirmationRequest(BaseModel):
    draft_revision: int = Field(ge=1)
    content: DraftContent

