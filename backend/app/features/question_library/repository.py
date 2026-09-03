"""Database access for current evaluation questions and batch command receipts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.lib.database import as_utc
from app.lib.database.models import (
    AgentRunAttemptRow,
    BatchUploadCommandRow,
    EvalQuestionRow,
    OperationJobRow,
    SceneRow,
)
from app.features.scenes.repository import new_id


@dataclass(frozen=True)
class QuestionRecord:
    id: str
    scene_id: str
    scene_name: str
    client_case_id: str
    title: str
    task_prompt: str
    reference_examples: list[dict[str, Any]]
    bad_cases: list[dict[str, Any]]
    reference_answer: str
    memory_materials: list[dict[str, Any]]
    criteria: list[dict[str, Any]] | None
    criteria_confirmed: bool
    status: str
    content_revision: int
    active_operation_id: str | None
    last_error: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    ever_published: bool


@dataclass(frozen=True)
class CommandReceipt:
    id: str
    scene_id: str
    command_id: str
    payload_hash: str
    status: str
    result: dict[str, Any] | None
    created_at: datetime
    completed_at: datetime | None


def _record(row: EvalQuestionRow, scene_name: str) -> QuestionRecord:
    return QuestionRecord(
        id=row.id,
        scene_id=row.scene_id,
        scene_name=scene_name,
        client_case_id=row.client_case_id,
        title=row.title,
        task_prompt=row.task_prompt,
        reference_examples=list(row.reference_examples_json or []),
        bad_cases=list(row.bad_cases_json or []),
        reference_answer=row.reference_answer,
        memory_materials=list(row.memory_materials_json or []),
        criteria=list(row.criteria_json) if row.criteria_json is not None else None,
        criteria_confirmed=bool(row.criteria_confirmed),
        status=row.status,
        content_revision=row.content_revision,
        active_operation_id=row.active_operation_id,
        last_error=row.last_error_json,
        created_at=as_utc(row.created_at),
        updated_at=as_utc(row.updated_at),
        published_at=as_utc(row.published_at) if row.published_at else None,
        ever_published=bool(row.ever_published),
    )


def _scene_names(session: Session, scene_ids: set[str]) -> dict[str, str]:
    if not scene_ids:
        return {}
    rows = session.execute(select(SceneRow).where(SceneRow.id.in_(scene_ids))).scalars().all()
    return {row.id: row.name for row in rows}


def create_question(
    session: Session,
    *,
    scene_id: str,
    client_case_id: str,
    title: str,
    task_prompt: str,
    reference_examples: list[dict[str, Any]],
    bad_cases: list[dict[str, Any]],
    reference_answer: str,
    memory_materials: list[dict[str, Any]],
    now: datetime,
) -> QuestionRecord:
    row = EvalQuestionRow(
        id=new_id(),
        scene_id=scene_id,
        client_case_id=client_case_id,
        title=title,
        task_prompt=task_prompt,
        reference_examples_json=reference_examples,
        bad_cases_json=bad_cases,
        reference_answer=reference_answer,
        memory_materials_json=memory_materials,
        criteria_json=None,
        criteria_confirmed=False,
        status="generating",
        content_revision=1,
        active_operation_id=None,
        last_error_json=None,
        created_at=now,
        updated_at=now,
        published_at=None,
        ever_published=False,
    )
    session.add(row)
    session.flush()
    scene_name = _scene_names(session, {scene_id}).get(scene_id, "")
    return _record(row, scene_name)


def get_question(session: Session, question_id: str) -> QuestionRecord | None:
    row = session.get(EvalQuestionRow, question_id)
    if row is None:
        return None
    scene_name = _scene_names(session, {row.scene_id}).get(row.scene_id, "")
    return _record(row, scene_name)


def list_questions(
    session: Session, *, scene_id: str, status: str | None = None
) -> list[QuestionRecord]:
    if not scene_id.strip():
        raise ValueError("scene_id is required for listing questions")
    statement = (
        select(EvalQuestionRow)
        .where(EvalQuestionRow.scene_id == scene_id)
        .order_by(EvalQuestionRow.created_at)
    )
    if status:
        statement = statement.where(EvalQuestionRow.status == status)
    rows = session.execute(statement).scalars().all()
    names = _scene_names(session, {row.scene_id for row in rows})
    return [_record(row, names.get(row.scene_id, "")) for row in rows]


def update_fields(
    session: Session,
    question_id: str,
    *,
    expected_revision: int,
    now: datetime,
    **fields: Any,
) -> QuestionRecord | None:
    """CAS update guarded by a conditional UPDATE.

    SQLite does not implement SELECT ... FOR UPDATE, so the row-level lock
    pattern cannot be used.  The conditional UPDATE is the portable
    compare-and-swap: when the stored revision no longer matches, ``rowcount``
    is 0 and the caller receives ``None``.
    """

    statement = (
        update(EvalQuestionRow)
        .where(
            EvalQuestionRow.id == question_id,
            EvalQuestionRow.content_revision == expected_revision,
        )
        .values(updated_at=now, **fields)
        .execution_options(synchronize_session=False)
    )
    if session.execute(statement).rowcount != 1:
        session.rollback()
        return None
    row = session.get(EvalQuestionRow, question_id)
    if row is None:  # pragma: no cover - deleted between update and read
        return None
    scene_name = _scene_names(session, {row.scene_id}).get(row.scene_id, "")
    return _record(row, scene_name)


def question_exists(session: Session, question_id: str) -> bool:
    return session.get(EvalQuestionRow, question_id) is not None


def delete_question_and_generation_history(session: Session, question_id: str) -> None:
    """Hard-delete a question plus its generation jobs and attempt records.

    ``operation_jobs`` references the question only through a loose
    ``target_id`` string, so the cleanup is explicit and scoped to this single
    question; it never touches sibling questions or batch receipts. Attempts
    are removed before their jobs to stay independent of FK cascade timing.
    """

    from sqlalchemy import delete

    job_ids = (
        session.execute(
            select(OperationJobRow.id).where(
                OperationJobRow.target_type == "eval_question",
                OperationJobRow.target_id == question_id,
            )
        )
        .scalars()
        .all()
    )
    if job_ids:
        session.execute(
            delete(AgentRunAttemptRow).where(AgentRunAttemptRow.operation_job_id.in_(job_ids))
        )
        session.execute(delete(OperationJobRow).where(OperationJobRow.id.in_(job_ids)))
    row = session.get(EvalQuestionRow, question_id)
    if row is not None:
        session.delete(row)


# ---------------------------------------------------------------------------
# Batch command receipts
# ---------------------------------------------------------------------------

def _receipt(row: BatchUploadCommandRow) -> CommandReceipt:
    return CommandReceipt(
        id=row.id,
        scene_id=row.scene_id,
        command_id=row.command_id,
        payload_hash=row.payload_hash,
        status=row.status,
        result=row.result_json,
        created_at=as_utc(row.created_at),
        completed_at=as_utc(row.completed_at) if row.completed_at else None,
    )


def get_command(session: Session, scene_id: str, command_id: str) -> CommandReceipt | None:
    row = session.execute(
        select(BatchUploadCommandRow).where(
            BatchUploadCommandRow.scene_id == scene_id,
            BatchUploadCommandRow.command_id == command_id,
        )
    ).scalar_one_or_none()
    return _receipt(row) if row else None


def reserve_command(
    session: Session, *, scene_id: str, credential_id: str | None, command_id: str, payload_hash: str, now: datetime
) -> CommandReceipt:
    row = BatchUploadCommandRow(
        id=new_id(),
        scene_id=scene_id,
        credential_id=credential_id,
        command_id=command_id,
        payload_hash=payload_hash,
        status="creating",
        created_at=now,
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ValueError("COMMAND_EXISTS") from exc
    return _receipt(row)


def complete_command(
    session: Session, receipt_id: str, *, result: dict[str, Any], now: datetime
) -> None:
    row = session.get(BatchUploadCommandRow, receipt_id)
    if row is None:
        return
    row.status = "ready"
    row.result_json = result
    row.completed_at = now
    session.flush()


def release_command(session: Session, receipt_id: str) -> None:
    row = session.get(BatchUploadCommandRow, receipt_id)
    if row is not None and row.status == "creating":
        session.delete(row)
        session.flush()
