from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import hashlib
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from app.lib.database import as_utc, session_scope
from app.lib.database.models import AgentRunAttemptRow, OperationJobRow
from app.lib.settings import settings


class OperationJobStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    superseded = "superseded"
    projection_pending = "projection_pending"


class OperationCommandConflict(RuntimeError):
    """A command id was already used for another operation kind."""


OPERATION_KINDS = (
    "batch_analysis",
    "cocreation_start",
    "cocreation_resume",
    "cocreation_reproject",
    "authoring_process",
    "authoring_reproject",
    "rubric_process",
    "rubric_reproject",
    "coverage_review",
    "freeze_package",
)


@dataclass(frozen=True, slots=True)
class OperationJob:
    id: str
    kind: str
    target_type: str
    target_id: str
    command_id: str
    business_revision: int
    accepted_checkpoint_id: str | None
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
        accepted_checkpoint_id=row.accepted_checkpoint_id,
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


def _result_hash(result: dict[str, Any] | None) -> str | None:
    if result is None:
        return None
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _current_attempt(session, row: OperationJobRow) -> AgentRunAttemptRow | None:
    return session.scalar(
        select(AgentRunAttemptRow).where(
            AgentRunAttemptRow.operation_job_id == row.id,
            AgentRunAttemptRow.attempt_number == row.attempts,
        )
    )


def create_or_get(
    *,
    kind: str,
    target_type: str,
    target_id: str,
    command_id: str,
    business_revision: int = 0,
    accepted_checkpoint_id: str | None = None,
    max_attempts: int | None = None,
) -> OperationJob:
    if kind not in OPERATION_KINDS:
        raise ValueError(f"unsupported operation kind: {kind}")
    if not command_id.strip():
        raise ValueError("command_id is required")
    if max_attempts is not None and max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    now = _utc_now()
    row = OperationJobRow(
        id=str(uuid4()),
        kind=kind,
        target_type=target_type,
        target_id=target_id,
        command_id=command_id,
        business_revision=business_revision,
        accepted_checkpoint_id=accepted_checkpoint_id,
        status=OperationJobStatus.queued.value,
        attempts=0,
        max_attempts=(max_attempts if max_attempts is not None else settings.operation_max_attempts),
        available_at=now,
        created_at=now,
        updated_at=now,
    )
    try:
        with session_scope() as session:
            session.add(row)
            session.flush()
            return _to_record(row)
    except IntegrityError:
        with session_scope() as session:
            existing = session.scalar(
                select(OperationJobRow).where(
                    OperationJobRow.target_type == target_type,
                    OperationJobRow.target_id == target_id,
                    OperationJobRow.business_revision == business_revision,
                    OperationJobRow.command_id == command_id,
                )
            )
            if existing is None:
                raise
            if existing.kind != kind:
                raise OperationCommandConflict("command id already used for another operation kind")
            return _to_record(existing)


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
                    base_checkpoint_id=row.accepted_checkpoint_id,
                    status="running",
                    created_at=now,
                )
            )
            session.flush()
            return _to_record(row)
    return None


def complete(
    job_id: str,
    worker_id: str,
    result: dict[str, Any] | None = None,
) -> OperationJob:
    now = _utc_now()
    with session_scope() as session:
        row = session.get(OperationJobRow, job_id)
        if row is None:
            raise KeyError(job_id)
        if row.status != OperationJobStatus.running.value or row.worker_id != worker_id:
            raise ValueError("operation is not owned by this worker")
        row.status = OperationJobStatus.succeeded.value
        row.result_json = result
        row.lease_until = None
        row.worker_id = None
        row.finished_at = now
        row.updated_at = now
        attempt = _current_attempt(session, row)
        if attempt is not None:
            attempt.status = "succeeded"
            attempt.result_hash = _result_hash(result)
        session.flush()
        return _to_record(row)


def complete_if_current(
    job_id: str,
    worker_id: str,
    *,
    current_revision: int,
    current_accepted_checkpoint_id: str | None,
    result: dict[str, Any] | None = None,
) -> OperationJob:
    """Commit only when the business projection still matches the job base."""

    now = _utc_now()
    with session_scope() as session:
        row = session.get(OperationJobRow, job_id)
        if row is None:
            raise KeyError(job_id)
        if row.status != OperationJobStatus.running.value or row.worker_id != worker_id:
            raise ValueError("operation is not owned by this worker")
        if (
            row.business_revision != current_revision
            or row.accepted_checkpoint_id != current_accepted_checkpoint_id
        ):
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
            attempt.result_hash = _result_hash(result)
        session.flush()
        return _to_record(row)


def mark_projection_pending(
    job_id: str,
    worker_id: str,
    *,
    produced_checkpoint_id: str | None = None,
    result_hash: str | None = None,
    runtime_mode: str | None = None,
) -> OperationJob:
    now = _utc_now()
    with session_scope() as session:
        row = session.get(OperationJobRow, job_id)
        if row is None:
            raise KeyError(job_id)
        if row.status != OperationJobStatus.running.value or row.worker_id != worker_id:
            raise ValueError("operation is not owned by this worker")
        row.status = OperationJobStatus.projection_pending.value
        if runtime_mode is not None:
            result_payload = dict(row.result_json or {})
            result_payload["__worker_runtime_mode"] = runtime_mode
            row.result_json = result_payload
        row.lease_until = None
        row.worker_id = None
        row.updated_at = now
        attempt = _current_attempt(session, row)
        if attempt is not None:
            attempt.status = "projection_pending"
            if produced_checkpoint_id:
                attempt.produced_checkpoint_id = produced_checkpoint_id
            if result_hash:
                attempt.result_hash = result_hash
        session.flush()
        return _to_record(row)


def save_result(job_id: str, worker_id: str, result: dict[str, Any]) -> OperationJob:
    """Persist an internal result while the current Worker still owns a job.

    Authoring uses this only for a projection-pending handoff.  The payload is
    never returned by an API; it lets a later reproject operation commit an
    already-produced business result without calling the model again.
    """

    now = _utc_now()
    with session_scope() as session:
        row = session.get(OperationJobRow, job_id, with_for_update=True)
        if row is None:
            raise KeyError(job_id)
        if row.status != OperationJobStatus.running.value or row.worker_id != worker_id:
            raise ValueError("operation is not owned by this worker")
        row.result_json = dict(result)
        row.updated_at = now
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


def retry_failed(job_id: str) -> OperationJob:
    """Requeue a failed operation without creating a second command record."""

    now = _utc_now()
    with session_scope() as session:
        row = session.get(OperationJobRow, job_id)
        if row is None:
            raise KeyError(job_id)
        if row.status != OperationJobStatus.failed.value or row.attempts >= row.max_attempts:
            return _to_record(row)
        row.status = OperationJobStatus.queued.value
        row.available_at = now
        row.last_error_json = None
        row.finished_at = None
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


def release_expired() -> int:
    now = _utc_now()
    released = 0
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
            released += 1
    return released
