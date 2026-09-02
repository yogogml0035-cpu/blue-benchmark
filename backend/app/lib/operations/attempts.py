from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from app.lib.database import as_utc, session_scope
from app.lib.database.models import AgentRunAttemptRow


@dataclass(frozen=True, slots=True)
class AgentRunAttempt:
    id: str
    operation_job_id: str
    target_type: str
    target_id: str
    attempt_number: int
    status: str
    created_at: datetime


def _to_record(row: AgentRunAttemptRow) -> AgentRunAttempt:
    return AgentRunAttempt(
        id=row.id,
        operation_job_id=row.operation_job_id,
        target_type=row.target_type,
        target_id=row.target_id,
        attempt_number=row.attempt_number,
        status=row.status,
        created_at=as_utc(row.created_at),
    )


def get(attempt_id: str) -> AgentRunAttempt | None:
    with session_scope() as session:
        row = session.get(AgentRunAttemptRow, attempt_id)
        return _to_record(row) if row else None


def list_for_job(operation_job_id: str) -> list[AgentRunAttempt]:
    with session_scope() as session:
        rows = session.scalars(
            select(AgentRunAttemptRow)
            .where(AgentRunAttemptRow.operation_job_id == operation_job_id)
            .order_by(AgentRunAttemptRow.attempt_number)
        ).all()
        return [_to_record(row) for row in rows]
