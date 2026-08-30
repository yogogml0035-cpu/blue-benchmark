from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

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
    base_checkpoint_id: str | None
    produced_checkpoint_id: str | None
    result_hash: str | None
    status: str
    created_at: datetime


def _to_record(row: AgentRunAttemptRow) -> AgentRunAttempt:
    return AgentRunAttempt(
        id=row.id,
        operation_job_id=row.operation_job_id,
        target_type=row.target_type,
        target_id=row.target_id,
        attempt_number=row.attempt_number,
        base_checkpoint_id=row.base_checkpoint_id,
        produced_checkpoint_id=row.produced_checkpoint_id,
        result_hash=row.result_hash,
        status=row.status,
        created_at=as_utc(row.created_at),
    )


def create(
    *,
    operation_job_id: str,
    target_type: str,
    target_id: str,
    attempt_number: int,
    base_checkpoint_id: str | None = None,
) -> AgentRunAttempt:
    row = AgentRunAttemptRow(
        id=str(uuid4()),
        operation_job_id=operation_job_id,
        target_type=target_type,
        target_id=target_id,
        attempt_number=attempt_number,
        base_checkpoint_id=base_checkpoint_id,
        status="running",
        created_at=datetime.now(timezone.utc),
    )
    with session_scope() as session:
        session.add(row)
        session.flush()
        return _to_record(row)


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


def mark_produced(
    attempt_id: str,
    *,
    produced_checkpoint_id: str,
    result_hash: str,
    status: str = "produced",
) -> AgentRunAttempt:
    with session_scope() as session:
        row = session.get(AgentRunAttemptRow, attempt_id)
        if row is None:
            raise KeyError(attempt_id)
        row.produced_checkpoint_id = produced_checkpoint_id
        row.result_hash = result_hash
        row.status = status
        session.flush()
        return _to_record(row)
