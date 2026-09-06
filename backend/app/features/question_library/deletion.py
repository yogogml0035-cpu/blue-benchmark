"""Complete same-question deletion: freeze, cross-store cleanup, final commit.

Semantics (one-shot replacement of the old "204 = deleted" early-success):

* DELETE keeps every original gate (revision, generating, published-reopen,
  ever-published title confirmation) and then ATOMICALLY freezes the question
  (status ``deleting``) and registers a durable cleanup operation in the same
  business transaction. Acceptance is NOT completion.
* A cleanup worker (no model dependency) deletes every registered run thread's
  checkpoint data — all namespaces, pending writes, blobs and StateBackend
  files — through the locked C2 primitives, retrying on transient failures.
* Only after cross-store cleanup verifies zero residue does the final business
  transaction remove the question, its run events/thread registry and its
  generation history, and commit the cleanup job as succeeded. A minimal
  receipt (job id/status, no material content) survives for idempotency.
* While frozen, every write path (materials, criteria, publish, retry,
  resume, event replay) is refused; failures stay visible and retryable and
  never masquerade as generation failures.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from app.lib.operations import repository

CLEANUP_KIND = "question_cleanup"
CLEANUP_TARGET_TYPE = "question_deletion"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def cleanup_command_id(question_id: str, command_id: str, revision: int) -> str:
    seed = f"question-cleanup:{question_id}:{revision}:{command_id}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:40]
    return f"cleanup:{digest}"


def accept_delete(session, *, question_row, command_id: str, now: datetime) -> str:
    """Freeze the question and enqueue the durable cleanup job (same transaction).

    The job id is deterministic in (question, revision, command), so a replayed
    acceptance produces the identical operation instead of a second cleanup.
    """
    from app.lib.database.models import AgentRunAttemptRow, OperationJobRow
    from sqlalchemy import delete as sa_delete, select

    job_id = str(
        uuid.UUID(
            hashlib.sha256(
                cleanup_command_id(question_row.id, command_id, question_row.content_revision)
                .encode("utf-8")
            ).hexdigest()[:32]
        )
    )
    existing = session.execute(
        select(OperationJobRow).where(OperationJobRow.id == job_id)
    ).scalar_one_or_none()
    if existing is not None:
        if existing.status in (
            repository.OperationJobStatus.failed.value,
            repository.OperationJobStatus.superseded.value,
        ):
            # Retry after a failed cleanup: fresh attempt budget, same identity.
            session.execute(
                sa_delete(AgentRunAttemptRow).where(
                    AgentRunAttemptRow.operation_job_id == job_id
                )
            )
            existing.status = repository.OperationJobStatus.queued.value
            existing.attempts = 0
            existing.available_at = now
            existing.last_error_json = None
            existing.finished_at = None
            existing.updated_at = now
            session.flush()
        elif existing.status == repository.OperationJobStatus.succeeded.value:
            raise ValueError("CLEANUP_ALREADY_SUCCEEDED")
        question_row.status = "deleting"
        question_row.active_operation_id = job_id
        question_row.updated_at = now
        session.flush()
        return job_id

    row = OperationJobRow(
        id=job_id,
        kind=CLEANUP_KIND,
        target_type=CLEANUP_TARGET_TYPE,
        target_id=question_row.id,
        command_id=cleanup_command_id(question_row.id, command_id, question_row.content_revision),
        business_revision=question_row.content_revision,
        status=repository.OperationJobStatus.queued.value,
        attempts=0,
        max_attempts=_max_attempts(),
        available_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    question_row.status = "deleting"
    question_row.active_operation_id = job_id
    question_row.updated_at = now
    session.flush()
    return job_id


def _max_attempts() -> int:
    from app.lib.settings import settings

    # Cleanup must outlive transient checkpoint-database outages; give it a
    # larger budget than generation without becoming unbounded.
    return max(settings.operation_max_attempts, 5)


def _mark_attempt(session, job_row, status: str) -> None:
    from sqlalchemy import select

    from app.lib.database.models import AgentRunAttemptRow

    attempt = session.scalar(
        select(AgentRunAttemptRow).where(
            AgentRunAttemptRow.operation_job_id == job_row.id,
            AgentRunAttemptRow.attempt_number == job_row.attempts,
        )
    )
    if attempt is not None:
        attempt.status = status


def get_active_cleanup(question_id: str) -> repository.OperationJob | None:
    jobs = repository.list_for_target(CLEANUP_TARGET_TYPE, question_id)
    active = [
        job
        for job in jobs
        if job.status
        in (
            repository.OperationJobStatus.queued,
            repository.OperationJobStatus.running,
            repository.OperationJobStatus.failed,
        )
    ]
    if not active:
        return None
    return max(active, key=lambda job: job.created_at)


def process_question_cleanup(job: repository.OperationJob) -> dict[str, Any]:
    """Worker handler: cross-store cleanup, then the final business delete.

    Never touches a model provider. Checkpoint unavailability is retryable;
    the frozen question is never reopened by this path.
    """
    from sqlalchemy import select

    from app.features.question_library import run_streams
    from app.lib.database import session_scope
    from app.lib.database.models import EvalQuestionRow, OperationJobRow

    question_id = job.target_id

    with session_scope() as session:
        job_row = session.execute(
            select(OperationJobRow).where(OperationJobRow.id == job.id)
        ).scalar_one_or_none()
        if job_row is None or job_row.status not in ("queued", "running"):
            from app.lib.operations.worker import SupersededOperation

            raise SupersededOperation("清理任务已经被取代。")
        row = session.get(EvalQuestionRow, question_id)
        if row is None:
            # The business row is already gone (a previous attempt committed
            # the final transaction but lost ownership before recording it).
            # Verify no residue remains, then finish idempotently.
            threads: list[str] = []
        elif row.status != "deleting":
            from app.lib.ai_runtime.adapters import RubricGenerationFailure

            raise RubricGenerationFailure(
                "DELETE_STATE_INVALID",
                "题目不处于删除冻结状态，拒绝执行清理。",
                retryable=False,
            )
        else:
            threads = run_streams.list_question_threads(question_id)

    # Phase 1: external checkpoint cleanup (retryable, model-free).
    cleaned: list[str] = []
    if threads:
        cleaned = _cleanup_checkpoint_threads(threads)

    # Phase 2: final business transaction — remove everything and succeed.
    now = _utc_now()
    with session_scope() as session:
        job_row = session.execute(
            select(OperationJobRow)
            .where(OperationJobRow.id == job.id)
            .with_for_update()
        ).scalar_one_or_none()
        if (
            job_row is None
            or job_row.status != repository.OperationJobStatus.running.value
            or job_row.worker_id != job.worker_id
        ):
            # Ownership lost; the new owner redoes the (idempotent) cleanup.
            return {"cleaned_threads": len(cleaned)}
        row = session.get(EvalQuestionRow, question_id, with_for_update=True)
        if row is not None:
            if row.status != "deleting":
                from app.lib.ai_runtime.adapters import RubricGenerationFailure

                raise RubricGenerationFailure(
                    "DELETE_STATE_INVALID", "题目不处于删除冻结状态，拒绝最终删除。", retryable=False
                )
            run_streams.delete_question_run_rows(session, question_id)
            _delete_question_and_generation_history(session, question_id)
        job_row.status = repository.OperationJobStatus.succeeded.value
        job_row.result_json = {
            "cleaned_threads": len(cleaned),
            "question_removed": row is not None,
        }
        job_row.lease_until = None
        job_row.worker_id = None
        job_row.finished_at = now
        job_row.updated_at = now
        _mark_attempt(session, job_row, "succeeded")
    return {"cleaned_threads": len(cleaned)}


def _cleanup_checkpoint_threads(threads: list[str]) -> list[str]:
    """Delete every registered thread's checkpoint data; loud on residue."""
    from app.lib.ai_runtime import deep_runtime
    from app.lib.settings import settings

    if not settings.checkpoint_database_url.get_secret_value():
        # Threads were registered by a real runtime, so a missing checkpoint
        # configuration is a retryable infrastructure failure — never a silent
        # skip that would report success over retained originals.
        raise deep_runtime.DeepRuntimeError(
            "CHECKPOINT_DSN_MISSING",
            "存在运行线程但检查点库未配置，删除清理无法完成。",
            retryable=True,
        )
    cleaned: list[str] = []
    for thread_id in threads:
        session = deep_runtime.open_session(thread_id)
        try:
            deep_runtime.delete_thread_data(session)
        finally:
            session.close()
        cleaned.append(thread_id)
    return cleaned


def _delete_question_and_generation_history(session, question_id: str) -> None:
    """Hard-delete the frozen question row and its generation jobs/attempts.

    The cleanup job itself lives under ``target_type=question_deletion`` and
    is deliberately NOT matched by this generation-history query, so the
    completion receipt survives for idempotency and audit.
    """
    from sqlalchemy import delete as sa_delete, select

    from app.lib.database.models import AgentRunAttemptRow, EvalQuestionRow, OperationJobRow

    session.execute(sa_delete(EvalQuestionRow).where(EvalQuestionRow.id == question_id))
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
            sa_delete(AgentRunAttemptRow).where(AgentRunAttemptRow.operation_job_id.in_(job_ids))
        )
        session.execute(sa_delete(OperationJobRow).where(OperationJobRow.id.in_(job_ids)))
