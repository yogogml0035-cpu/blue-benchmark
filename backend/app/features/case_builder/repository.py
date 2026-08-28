from dataclasses import dataclass, field
from datetime import datetime

from app.features.case_builder.schemas import (
    Attachment,
    CandidateCase,
    CaseState,
    DraftContent,
    LastError,
    PendingQuestion,
)


@dataclass(slots=True)
class CaseRecord:
    id: str
    workspace_id: str
    title: str
    task_description: str | None
    attachment: Attachment
    parsed_text: str
    state: CaseState
    thread_id: str
    created_at: datetime
    updated_at: datetime
    draft_revision: int = 0
    pending_question: PendingQuestion | None = None
    draft: DraftContent | None = None
    last_error: LastError | None = None
    candidate_case: CandidateCase | None = None
    generation_attempts: int = 0
    answered_questions: dict[str, str] = field(default_factory=dict)
    mode: str = "question"


cases: dict[str, CaseRecord] = {}


def add(case: CaseRecord) -> None:
    cases[case.id] = case


def get(case_id: str) -> CaseRecord | None:
    return cases.get(case_id)


def reset() -> None:
    cases.clear()

