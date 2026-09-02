from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select, update

from app.lib.database import as_utc, session_scope
from app.lib.database.models import AgentRunAttemptRow, OperationJobRow
from app.lib.settings import settings


class OperationJobStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    superseded = "superseded"


OPERATION_KINDS = ("rubric_generation",)


@dataclass(frozen=True, slots=True)
class OperationJob:
    id: str
    kind: str
    target_type: str
    target_id: str
    command_id: str
    business_revision: int
    status: OperationJobStatus
    attempts: int
    max_attempts: int
    available_at: datetime
    lease_until: datetime | None
    worker_id: str | None
    last_error: dict[str, Any] | None
    result: dict[str, Any] | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_record(row: OperationJobRow) -> OperationJob:
    return OperationJob(
        id=row.id,
        kind=row.kind,
        target_type=row.target_type,
        target_id=row.target_id,
        command_id=row.command_id,
        business_revision=row.business_revision,
        status=OperationJobStatus(row.status),
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        available_at=as_utc(row.available_at),
        lease_until=as_utc(row.lease_until) if row.lease_until else None,
        worker_id=row.worker_id,
        last_error=row.last_error_json,
        result=row.result_json,
        created_at=as_utc(row.created_at),
        started_at=as_utc(row.started_at) if row.started_at else None,
        finished_at=as_utc(row.finished_at) if row.finished_at else None,
        updated_at=as_utc(row.updated_at),
    )


def _current_attempt(session, row: OperationJobRow) -> AgentRunAttemptRow | None:
    return session.scalar(
        select(AgentRunAttemptRow).where(
            AgentRunAttemptRow.operation_job_id == row.id,
            AgentRunAttemptRow.attempt_number == row.attempts,
        )
    )


def get(job_id: str) -> OperationJob | None:
    with session_scope() as session:
        row = session.get(OperationJobRow, job_id)
        return _to_record(row) if row else None


def list_for_target(target_type: str, target_id: str) -> list[OperationJob]:
    with session_scope() as session:
        rows = session.scalars(
            select(OperationJobRow)
            .where(
                OperationJobRow.target_type == target_type,
                OperationJobRow.target_id == target_id,
            )
            .order_by(OperationJobRow.updated_at.desc(), OperationJobRow.created_at.desc())
        ).all()
        return [_to_record(row) for row in rows]


def claim_next(worker_id: str, lease_seconds: int | None = None) -> OperationJob | None:
    now = _utc_now()
    lease_until = now + timedelta(
        seconds=lease_seconds if lease_seconds is not None else settings.operation_lease_seconds
    )
    for _ in range(3):
        with session_scope() as session:
            candidate = session.scalar(
                select(OperationJobRow)
                .where(
                    OperationJobRow.available_at <= now,
                    OperationJobRow.attempts < OperationJobRow.max_attempts,
                    or_(
                        OperationJobRow.status == OperationJobStatus.queued.value,
                        (
                            (OperationJobRow.status == OperationJobStatus.running.value)
                            & (OperationJobRow.lease_until < now)
                        ),
                    ),
                )
                .order_by(OperationJobRow.created_at)
                .with_for_update(skip_locked=True)
            )
            if candidate is None:
                return None
            result = session.execute(
                update(OperationJobRow)
                .where(
                    OperationJobRow.id == candidate.id,
                    OperationJobRow.attempts == candidate.attempts,
                    or_(
                        OperationJobRow.status == OperationJobStatus.queued.value,
                        (
                            (OperationJobRow.status == OperationJobStatus.running.value)
                            & (OperationJobRow.lease_until < now)
                        ),
                    ),
                )
                .values(
                    status=OperationJobStatus.running.value,
                    attempts=OperationJobRow.attempts + 1,
                    worker_id=worker_id,
                    lease_until=lease_until,
                    started_at=candidate.started_at or now,
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                continue
            session.expire(candidate)
            row = session.get(OperationJobRow, candidate.id)
            if row is None:
                return None
            session.add(
                AgentRunAttemptRow(
                    id=str(uuid4()),
                    operation_job_id=row.id,
                    target_type=row.target_type,
                    target_id=row.target_id,
                    attempt_number=row.attempts,
                    status="running",
                    created_at=now,
                )
            )
            session.flush()
            return _to_record(row)
    return None


def complete_if_current(
    job_id: str,
    worker_id: str,
    *,
    current_revision: int,
    result: dict[str, Any] | None = None,
) -> OperationJob:
    """Commit only when the business revision still matches the job base."""

    now = _utc_now()
    with session_scope() as session:
        row = session.get(OperationJobRow, job_id)
        if row is None:
            raise KeyError(job_id)
        if row.status != OperationJobStatus.running.value or row.worker_id != worker_id:
            raise ValueError("operation is not owned by this worker")
        if row.business_revision != current_revision:
            row.status = OperationJobStatus.superseded.value
            row.last_error_json = {"code": "SUPERSEDED", "message": "业务版本已经更新。"}
            row.lease_until = None
            row.worker_id = None
            row.finished_at = now
            row.updated_at = now
            attempt = _current_attempt(session, row)
            if attempt is not None:
                attempt.status = "superseded"
            session.flush()
            return _to_record(row)
        row.status = OperationJobStatus.succeeded.value
        row.result_json = result
        row.lease_until = None
        row.worker_id = None
        row.finished_at = now
        row.updated_at = now
        attempt = _current_attempt(session, row)
        if attempt is not None:
            attempt.status = "succeeded"
        session.flush()
        return _to_record(row)


def renew(job_id: str, worker_id: str, lease_seconds: int | None = None) -> OperationJob:
    now = _utc_now()
    with session_scope() as session:
        row = session.get(OperationJobRow, job_id)
        if row is None:
            raise KeyError(job_id)
        if row.status != OperationJobStatus.running.value or row.worker_id != worker_id:
            raise ValueError("operation is not owned by this worker")
        row.lease_until = now + timedelta(
            seconds=lease_seconds if lease_seconds is not None else settings.operation_lease_seconds
        )
        row.updated_at = now
        session.flush()
        return _to_record(row)


def fail(
    job_id: str,
    worker_id: str,
    error: dict[str, Any],
    *,
    retryable: bool,
    retry_after_seconds: int = 0,
) -> OperationJob:
    now = _utc_now()
    with session_scope() as session:
        row = session.get(OperationJobRow, job_id)
        if row is None:
            raise KeyError(job_id)
        if row.status != OperationJobStatus.running.value or row.worker_id != worker_id:
            raise ValueError("operation is not owned by this worker")
        row.last_error_json = error
        row.lease_until = None
        row.worker_id = None
        if retryable and row.attempts < row.max_attempts:
            row.status = OperationJobStatus.queued.value
            row.available_at = now + timedelta(seconds=max(0, retry_after_seconds))
        else:
            row.status = OperationJobStatus.failed.value
            row.finished_at = now
        attempt = _current_attempt(session, row)
        if attempt is not None:
            attempt.status = "retryable_failed" if row.status == OperationJobStatus.queued.value else "failed"
        row.updated_at = now
        session.flush()
        return _to_record(row)


def supersede(job_id: str, worker_id: str, reason: str) -> OperationJob:
    now = _utc_now()
    with session_scope() as session:
        row = session.get(OperationJobRow, job_id)
        if row is None:
            raise KeyError(job_id)
        if row.status != OperationJobStatus.running.value or row.worker_id != worker_id:
            raise ValueError("operation is not owned by this worker")
        row.status = OperationJobStatus.superseded.value
        row.last_error_json = {"code": "SUPERSEDED", "message": reason}
        row.lease_until = None
        row.worker_id = None
        row.finished_at = now
        row.updated_at = now
        attempt = _current_attempt(session, row)
        if attempt is not None:
            attempt.status = "superseded"
        session.flush()
        return _to_record(row)


def release_expired() -> tuple[int, list[OperationJob]]:
    """Requeue or fail lease-expired jobs.

    Returns the count and the jobs that transitioned to terminal ``failed``;
    the worker projects those failures onto their business targets.
    """

    now = _utc_now()
    released = 0
    terminal: list[OperationJob] = []
    with session_scope() as session:
        rows = session.scalars(
            select(OperationJobRow).where(
                OperationJobRow.status == OperationJobStatus.running.value,
                OperationJobRow.lease_until < now,
            )
        ).all()
        for row in rows:
            row.status = (
                OperationJobStatus.queued.value
                if row.attempts < row.max_attempts
                else OperationJobStatus.failed.value
            )
            row.worker_id = None
            row.lease_until = None
            row.updated_at = now
            attempt = _current_attempt(session, row)
            if attempt is not None:
                attempt.status = "lease_expired" if row.status == OperationJobStatus.queued.value else "failed"
            if row.status == OperationJobStatus.failed.value:
                row.finished_at = now
                terminal.append(_to_record(row))
            released += 1
    return released, terminal
