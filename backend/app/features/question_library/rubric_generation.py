"""Worker-side rubric generation: adapter call, business validation, CAS commit."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from app.lib.ai_runtime.adapters import (
    RubricGenerationFailure,
    RubricGenerationInput,
    RubricGenerationResult,
    get_adapters,
)
from app.lib.database import session_scope
from app.lib.database.models import EvalQuestionRow, OperationJobRow
from app.lib.operations import repository

TARGET_TYPE = "eval_question"


def derived_command_id(prefix: str, *parts: str) -> str:
    """Build a bounded, collision-safe command id from unbounded inputs.

    ``operation_jobs.command_id`` is limited to 255 characters; the raw
    concatenation of an external command id (up to 255) and a client case id
    (up to 128) would overflow on PostgreSQL. Hashing keeps the id stable and
    short regardless of input length.
    """

    seed = "\u0000".join(parts)
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:40]
    return f"{prefix}:{digest}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_generation_input(row: EvalQuestionRow) -> RubricGenerationInput:
    return RubricGenerationInput(
        task_prompt=row.task_prompt,
        reference_examples=[
            {
                "source_name": item.get("source_name"),
                "content_text": item.get("content_text", ""),
            }
            for item in (row.reference_examples_json or [])
        ],
        bad_cases=[
            {
                "content_text": item.get("content_text", ""),
                "teacher_feedback_texts": list(item.get("teacher_feedback_texts") or []),
                "reason_summary": item.get("reason_summary"),
            }
            for item in (row.bad_cases_json or [])
        ],
        reference_answer=row.reference_answer,
        memory_materials=[
            {
                "source_label": item.get("source_label"),
                "content_text": item.get("content_text", ""),
            }
            for item in (row.memory_materials_json or [])
        ],
    )


def normalize_criteria(result: RubricGenerationResult) -> list[dict[str, Any]]:
    """Assign stable ids and apply deterministic business validation."""

    from app.features.question_library import rubric_rules

    criteria: list[dict[str, Any]] = []
    for index, item in enumerate(result.criteria):
        criterion = item.criterion.strip()
        rubric_rules.validate_criterion_text(criterion)
        criteria.append(
            {
                "id": f"criterion-{index + 1}",
                "criterion": criterion,
                "pass_score": int(item.pass_score),
            }
        )
    return criteria


def process_rubric_generation(job: repository.OperationJob) -> dict[str, Any]:
    from sqlalchemy import select

    from app.lib.database.models import OperationJobRow

    # Fencing check before the (expensive) AI call: a job that is no longer
    # queued/running was superseded while waiting and must not spend a call.
    with session_scope() as session:
        job_row = session.execute(
            select(OperationJobRow).where(OperationJobRow.id == job.id)
        ).scalar_one_or_none()
        if (
            job_row is None
            or job_row.status not in ("queued", "running")
        ):
            from app.lib.operations.worker import SupersededOperation

            raise SupersededOperation("任务已经被取代。")
        row = session.get(EvalQuestionRow, job.target_id)
        if row is None or row.active_operation_id != job.id:
            from app.lib.operations.worker import SupersededOperation

            raise SupersededOperation("题目已经更新或删除。")
        materials = build_generation_input(row)

    result = get_adapters().rubric_generator.generate(materials)
    try:
        criteria = normalize_criteria(result)
    except ValueError as exc:
        raise RubricGenerationFailure(
            "AI_OUTPUT_INVALID", f"AI 输出的评分标准不可执行：{exc}", retryable=True
        ) from exc

    if not commit_generation_result(job, criteria):
        from app.lib.operations.worker import SupersededOperation

        raise SupersededOperation("题目材料已经更新，本轮生成作废。")
    return {"criteria_count": len(criteria)}


def commit_generation_result(
    job: repository.OperationJob, criteria: list[dict[str, Any]]
) -> bool:
    """Atomically commit criteria and complete the job in ONE transaction.

    The fencing predicate requires the job to still be ``running`` under the
    current worker AND the question to still point at this job with the same
    content revision, so a lease-expired duplicate or a stale generation can
    never overwrite committed criteria or later admin edits.
    """

    from sqlalchemy import select

    from app.lib.database.models import AgentRunAttemptRow, OperationJobRow

    def _mark_attempt(session, job_row: OperationJobRow, status: str) -> None:
        attempt = session.scalar(
            select(AgentRunAttemptRow).where(
                AgentRunAttemptRow.operation_job_id == job_row.id,
                AgentRunAttemptRow.attempt_number == job_row.attempts,
            )
        )
        if attempt is not None:
            attempt.status = status

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
            or job_row.business_revision != job.business_revision
        ):
            return False
        row = session.get(EvalQuestionRow, job.target_id, with_for_update=True)
        if (
            row is None
            or row.content_revision != job.business_revision
            or row.active_operation_id != job.id
        ):
            job_row.status = repository.OperationJobStatus.superseded.value
            job_row.last_error_json = {"code": "SUPERSEDED", "message": "业务版本已经更新。"}
            job_row.lease_until = None
            job_row.worker_id = None
            job_row.finished_at = now
            job_row.updated_at = now
            _mark_attempt(session, job_row, "superseded")
            return True
        row.criteria_json = criteria
        row.criteria_confirmed = False
        row.status = "pending_review"
        row.last_error_json = None
        row.active_operation_id = None
        row.updated_at = now
        job_row.status = repository.OperationJobStatus.succeeded.value
        job_row.result_json = {
            "criteria_count": len(criteria),
            "__worker_runtime_mode": _runtime_mode_marker(),
        }
        job_row.lease_until = None
        job_row.worker_id = None
        job_row.finished_at = now
        job_row.updated_at = now
        _mark_attempt(session, job_row, "succeeded")
    return True


def _runtime_mode_marker() -> str:
    from app.lib.settings import settings

    return settings.ai_runtime_mode


def mark_generation_failed(
    job: repository.OperationJob, error: dict[str, Any], *, worker_id: str
) -> None:
    """Best-effort projection: flip the question to generation_failed.

    Only applies when the question still points at this exact job and content
    revision, so a newer round is never overwritten by an older failure.
    """

    try:
        now = _utc_now()
        with session_scope() as session:
            row = session.get(EvalQuestionRow, job.target_id, with_for_update=True)
            if (
                row is None
                or row.active_operation_id != job.id
                or row.content_revision != job.business_revision
            ):
                return
            row.status = "generation_failed"
            row.last_error_json = {"code": error.get("code", "GENERATION_FAILED"), "message": error.get("message", "")}
            row.active_operation_id = None
            row.updated_at = now
    except Exception:
        # The OperationJob remains authoritative; projection cleanup is advisory.
        pass


def enqueue_generation(
    session, *, question_id: str, content_revision: int, command_id: str
) -> str:
    """Create (or revive) the idempotent generation job in the caller's transaction.

    The id is deterministic in (question, revision, command), so a replayed
    transaction produces the identical job identity. When a failed job with
    the same identity already exists (administrator retry with the same
    command), it is requeued with a fresh attempt budget instead of inserting
    a duplicate row.
    """

    from sqlalchemy import delete, select

    from app.lib.database.models import AgentRunAttemptRow, OperationJobRow

    seed = f"rubric-generation:{question_id}:{content_revision}:{command_id}"
    job_id = str(uuid.UUID(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]))
    now = _utc_now()
    existing = session.execute(
        select(OperationJobRow).where(OperationJobRow.id == job_id)
    ).scalar_one_or_none()
    if existing is not None:
        if existing.status in (
            repository.OperationJobStatus.failed.value,
            repository.OperationJobStatus.superseded.value,
        ):
            # A revived round starts from a clean attempt budget, so its
            # historical attempt rows must go: ``claim_next`` re-derives
            # attempt numbers from zero and the (job_id, attempt_number)
            # unique constraint would otherwise poison the queue.
            session.execute(
                delete(AgentRunAttemptRow).where(
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
            return job_id
        if existing.status in (
            repository.OperationJobStatus.queued.value,
            repository.OperationJobStatus.running.value,
        ):
            return job_id
        raise ValueError("GENERATION_JOB_CONFLICT")
    row = OperationJobRow(
        id=job_id,
        kind="rubric_generation",
        target_type=TARGET_TYPE,
        target_id=question_id,
        command_id=command_id,
        business_revision=content_revision,
        status=repository.OperationJobStatus.queued.value,
        attempts=0,
        max_attempts=_max_attempts(),
        available_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    return job_id


def _max_attempts() -> int:
    from app.lib.settings import settings

    return settings.operation_max_attempts
