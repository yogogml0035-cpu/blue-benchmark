from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select

from app.features.case_builder.schemas import (
    Attachment,
    CandidateCase,
    CaseState,
    DraftContent,
    LastError,
    PendingQuestion,
)
from app.lib.database import as_utc, session_scope
from app.lib.database.models import CaseRow


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


def _json(value):
    return value.model_dump(mode="json") if value is not None else None


def _from_json(model, value):
    return model.model_validate(value) if value is not None else None


def _to_record(row: CaseRow) -> CaseRecord:
    return CaseRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        title=row.title,
        task_description=row.task_description,
        attachment=Attachment.model_validate(row.attachment_json),
        parsed_text=row.parsed_text,
        state=CaseState(row.state),
        thread_id=row.thread_id,
        created_at=as_utc(row.created_at),
        updated_at=as_utc(row.updated_at),
        draft_revision=row.draft_revision,
        pending_question=_from_json(PendingQuestion, row.pending_question_json),
        draft=_from_json(DraftContent, row.draft_json),
        last_error=_from_json(LastError, row.last_error_json),
        candidate_case=_from_json(CandidateCase, row.candidate_case_json),
        generation_attempts=row.generation_attempts,
        answered_questions=dict(row.answered_questions_json or {}),
        mode=row.mode,
    )


def _to_row(case: CaseRecord) -> CaseRow:
    return CaseRow(
        id=case.id,
        workspace_id=case.workspace_id,
        title=case.title,
        task_description=case.task_description,
        attachment_json=case.attachment.model_dump(mode="json"),
        parsed_text=case.parsed_text,
        state=case.state.value,
        thread_id=case.thread_id,
        created_at=case.created_at,
        updated_at=case.updated_at,
        draft_revision=case.draft_revision,
        pending_question_json=_json(case.pending_question),
        draft_json=_json(case.draft),
        last_error_json=_json(case.last_error),
        candidate_case_json=_json(case.candidate_case),
        generation_attempts=case.generation_attempts,
        answered_questions_json=dict(case.answered_questions),
        mode=case.mode,
    )


def add(case: CaseRecord) -> None:
    with session_scope() as session:
        session.add(_to_row(case))


def save(case: CaseRecord) -> None:
    with session_scope() as session:
        row = session.get(CaseRow, case.id)
        if row is None:
            session.add(_to_row(case))
            return
        values = _to_row(case)
        for field_name in (
            "workspace_id",
            "title",
            "task_description",
            "attachment_json",
            "parsed_text",
            "state",
            "thread_id",
            "created_at",
            "updated_at",
            "draft_revision",
            "pending_question_json",
            "draft_json",
            "last_error_json",
            "candidate_case_json",
            "generation_attempts",
            "answered_questions_json",
            "mode",
        ):
            setattr(row, field_name, getattr(values, field_name))


def get(case_id: str) -> CaseRecord | None:
    with session_scope() as session:
        row = session.scalar(select(CaseRow).where(CaseRow.id == case_id))
        return _to_record(row) if row else None


def reset() -> None:
    from app.lib.database import clear_business_data

    clear_business_data()
