"""Persistence boundary for mutable rubric drafts and published snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.lib.database import as_utc, session_scope
from app.lib.database.models import (
    BenchmarkQuestionDraftRow,
    BenchmarkQuestionRevisionRow,
    RubricDraftRow,
    OperationJobRow,
)


class RepositoryConflict(RuntimeError):
    pass


class StaleRubric(RepositoryConflict):
    pass


@dataclass(frozen=True, slots=True)
class RubricDraftRecord:
    id: str
    workspace_id: str
    question_draft_id: str
    status: str
    revision: int
    source_question_revision: int
    source_question_hash: str
    rubric: dict[str, Any] | None
    pending_question: dict[str, Any] | None
    command_receipts: dict[str, Any]
    active_operation_id: str | None
    confirmed_by: str | None
    confirmed_at: datetime | None
    last_error: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class QuestionRevisionRecord:
    id: str
    workspace_id: str
    question_draft_id: str
    revision_number: int
    source_question_revision: int
    source_question_hash: str
    contract_revision_id: str | None
    question_snapshot: dict[str, Any]
    bad_samples: list[dict[str, Any]]
    reference_answer_text: str
    rubric: dict[str, Any]
    pass_threshold: int
    content_sha256: str
    publication_status: str
    published_by: str
    published_at: datetime
    created_at: datetime


def now() -> datetime:
    return datetime.now(timezone.utc)


def payload_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _draft(row: RubricDraftRow) -> RubricDraftRecord:
    return RubricDraftRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        question_draft_id=row.question_draft_id,
        status=row.status,
        revision=row.revision,
        source_question_revision=row.source_question_revision,
        source_question_hash=row.source_question_hash,
        rubric=dict(row.rubric_json) if row.rubric_json else None,
        pending_question=dict(row.pending_question_json) if row.pending_question_json else None,
        command_receipts=dict(row.command_receipts_json or {}),
        active_operation_id=row.active_operation_id,
        confirmed_by=row.confirmed_by,
        confirmed_at=as_utc(row.confirmed_at) if row.confirmed_at else None,
        last_error=dict(row.last_error_json) if row.last_error_json else None,
        created_at=as_utc(row.created_at),
        updated_at=as_utc(row.updated_at),
    )


def _revision(row: BenchmarkQuestionRevisionRow) -> QuestionRevisionRecord:
    return QuestionRevisionRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        question_draft_id=row.question_draft_id,
        revision_number=row.revision_number,
        source_question_revision=row.source_question_revision,
        source_question_hash=row.source_question_hash,
        contract_revision_id=row.contract_revision_id,
        question_snapshot=dict(row.question_snapshot_json or {}),
        bad_samples=[dict(item) for item in (row.bad_samples_json or []) if isinstance(item, dict)],
        reference_answer_text=row.reference_answer_text,
        rubric=dict(row.rubric_json or {}),
        pass_threshold=row.pass_threshold,
        content_sha256=row.content_sha256,
        publication_status=row.publication_status,
        published_by=row.published_by,
        published_at=as_utc(row.published_at),
        created_at=as_utc(row.created_at),
    )


def _receipt(row: RubricDraftRow, command_id: str, digest: str) -> bool:
    item = (row.command_receipts_json or {}).get(command_id)
    if item is None:
        return False
    if item.get("payload_hash") != digest:
        raise RepositoryConflict("rubric command payload conflicts")
    return True


def _remember(row: RubricDraftRow, command_id: str, digest: str) -> None:
    receipts = dict(row.command_receipts_json or {})
    receipts[command_id] = {"payload_hash": digest}
    row.command_receipts_json = receipts


def _remember_result(
    row: RubricDraftRow,
    command_id: str,
    digest: str,
    result: dict[str, Any],
) -> None:
    receipts = dict(row.command_receipts_json or {})
    receipts[command_id] = {"payload_hash": digest, **result}
    row.command_receipts_json = receipts


def _current_question(
    session,
    question_draft_id: str,
    source_question_revision: int,
    source_question_hash: str,
) -> BenchmarkQuestionDraftRow:
    question = session.scalar(
        select(BenchmarkQuestionDraftRow)
        .where(BenchmarkQuestionDraftRow.id == question_draft_id)
        .with_for_update()
    )
    if (
        question is None
        or question.status != "input_answer_confirmed"
        or question.confirmed_revision != source_question_revision
        or question.confirmed_hash != source_question_hash
    ):
        raise StaleRubric("confirmed question snapshot is stale")
    return question


def get_draft(rubric_id: str) -> RubricDraftRecord | None:
    with session_scope() as session:
        row = session.get(RubricDraftRow, rubric_id)
        return _draft(row) if row else None


def get_by_question(question_draft_id: str) -> RubricDraftRecord | None:
    with session_scope() as session:
        row = session.scalar(
            select(RubricDraftRow).where(
                RubricDraftRow.question_draft_id == question_draft_id
            )
        )
        return _draft(row) if row else None


def list_revisions(question_draft_id: str) -> list[QuestionRevisionRecord]:
    with session_scope() as session:
        rows = session.scalars(
            select(BenchmarkQuestionRevisionRow)
            .where(
                BenchmarkQuestionRevisionRow.question_draft_id == question_draft_id,
                BenchmarkQuestionRevisionRow.publication_status == "published",
            )
            .order_by(BenchmarkQuestionRevisionRow.revision_number.desc())
        ).all()
        return [_revision(row) for row in rows]


def list_published_revisions(workspace_id: str) -> list[QuestionRevisionRecord]:
    with session_scope() as session:
        rows = session.scalars(
            select(BenchmarkQuestionRevisionRow)
            .where(
                BenchmarkQuestionRevisionRow.workspace_id == workspace_id,
                BenchmarkQuestionRevisionRow.publication_status == "published",
            )
            .order_by(
                BenchmarkQuestionRevisionRow.published_at.desc(),
                BenchmarkQuestionRevisionRow.id.desc(),
            )
        ).all()
        return [_revision(row) for row in rows]


def list_current_active_revisions(workspace_id: str) -> list[QuestionRevisionRecord]:
    with session_scope() as session:
        rows = session.scalars(
            select(BenchmarkQuestionRevisionRow)
            .join(BenchmarkQuestionDraftRow, BenchmarkQuestionDraftRow.id == BenchmarkQuestionRevisionRow.question_draft_id)
            .where(
                BenchmarkQuestionRevisionRow.workspace_id == workspace_id,
                BenchmarkQuestionRevisionRow.publication_status == "published",
                BenchmarkQuestionDraftRow.lifecycle_status == "active",
                BenchmarkQuestionDraftRow.active_revision_id == BenchmarkQuestionRevisionRow.id,
            )
            .order_by(BenchmarkQuestionRevisionRow.id)
        ).all()
        return [_revision(row) for row in rows]


def get_revision(revision_id: str) -> QuestionRevisionRecord | None:
    with session_scope() as session:
        row = session.scalar(
            select(BenchmarkQuestionRevisionRow).where(
                BenchmarkQuestionRevisionRow.id == revision_id,
                BenchmarkQuestionRevisionRow.publication_status == "published",
            )
        )
        return _revision(row) if row else None


def get_revision_any(revision_id: str) -> QuestionRevisionRecord | None:
    """Read a staged revision for the publish finalizer only."""

    with session_scope() as session:
        row = session.get(BenchmarkQuestionRevisionRow, revision_id)
        return _revision(row) if row else None


def mark_revision_published(revision_id: str) -> QuestionRevisionRecord:
    with session_scope() as session:
        row = session.scalar(
            select(BenchmarkQuestionRevisionRow)
            .where(BenchmarkQuestionRevisionRow.id == revision_id)
            .with_for_update()
        )
        if row is None:
            raise KeyError(revision_id)
        row.publication_status = "published"
        session.flush()
        return _revision(row)


def create_or_reset(
    *,
    workspace_id: str,
    question_draft_id: str,
    source_question_revision: int,
    source_question_hash: str,
    command_id: str,
    digest: str,
) -> tuple[RubricDraftRecord, bool]:
    timestamp = now()
    try:
        with session_scope() as session:
            _current_question(
                session,
                question_draft_id,
                source_question_revision,
                source_question_hash,
            )
            row = session.scalar(
                select(RubricDraftRow)
                .where(RubricDraftRow.question_draft_id == question_draft_id)
                .with_for_update()
            )
            if row is not None and _receipt(row, command_id, digest):
                return _draft(row), True
            if row is None:
                row = RubricDraftRow(
                    id=str(uuid4()),
                    workspace_id=workspace_id,
                    question_draft_id=question_draft_id,
                    status="queued",
                    revision=0,
                    source_question_revision=source_question_revision,
                    source_question_hash=source_question_hash,
                    rubric_json=None,
                    pending_question_json=None,
                    command_receipts_json={},
                    active_operation_id=None,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                session.add(row)
            else:
                if row.workspace_id != workspace_id:
                    raise RepositoryConflict("rubric draft belongs to another workspace")
                if row.status == "processing" and row.active_operation_id:
                    raise RepositoryConflict("rubric draft already has an active operation")
                if row.status in {"confirmed", "published"} and (
                    row.source_question_revision == source_question_revision
                    and row.source_question_hash == source_question_hash
                ):
                    _remember(row, command_id, digest)
                    return _draft(row), True
                row.source_question_revision = source_question_revision
                row.source_question_hash = source_question_hash
                row.status = "queued"
                row.rubric_json = None
                row.pending_question_json = None
                row.active_operation_id = None
                row.confirmed_by = None
                row.confirmed_at = None
                row.last_error_json = None
                row.revision += 1
                row.updated_at = timestamp
            _remember(row, command_id, digest)
            session.flush()
            return _draft(row), False
    except IntegrityError:
        row = get_by_question(question_draft_id)
        if row is None:
            raise RepositoryConflict("rubric draft was updated concurrently") from None
        return row, True


def set_active_operation(
    rubric_id: str,
    operation_id: str,
    *,
    expected_revision: int,
) -> RubricDraftRecord:
    with session_scope() as session:
        row = session.scalar(
            select(RubricDraftRow)
            .where(RubricDraftRow.id == rubric_id)
            .with_for_update()
        )
        operation = session.get(OperationJobRow, operation_id, with_for_update=True)
        if row is None or operation is None:
            raise KeyError(rubric_id)
        if operation.target_type != "rubric_draft" or operation.target_id != rubric_id:
            raise RepositoryConflict("rubric operation target does not match")
        if row.revision != expected_revision:
            return _draft(row)
        if row.active_operation_id and row.active_operation_id != operation_id:
            raise RepositoryConflict("rubric draft already has another operation")
        if operation.status in {"queued", "running"}:
            row.active_operation_id = operation_id
            row.status = "processing"
            row.pending_question_json = None
        elif operation.status in {"failed", "superseded", "succeeded"}:
            row.active_operation_id = None
            row.status = "failed"
            row.last_error_json = {"code": "RUBRIC_PROCESS_FAILED"}
        elif operation.status == "projection_pending":
            row.active_operation_id = None
            row.status = "projection_pending"
        else:
            raise RepositoryConflict("rubric operation has an unknown status")
        row.updated_at = now()
        session.flush()
        return _draft(row)


def patch_rubric(
    rubric_id: str,
    *,
    expected_revision: int,
    source_question_revision: int,
    source_question_hash: str,
    command_id: str,
    digest: str,
    rubric: dict[str, Any],
) -> RubricDraftRecord:
    timestamp = now()
    with session_scope() as session:
        row = session.get(RubricDraftRow, rubric_id)
        if row is None:
            raise KeyError(rubric_id)
        _current_question(session, row.question_draft_id, source_question_revision, source_question_hash)
        row = session.scalar(select(RubricDraftRow).where(RubricDraftRow.id == rubric_id).with_for_update())
        if row is None:
            raise KeyError(rubric_id)
        if _receipt(row, command_id, digest):
            return _draft(row)
        if row.source_question_revision != source_question_revision or row.source_question_hash != source_question_hash:
            raise StaleRubric("rubric source question changed")
        if row.revision != expected_revision:
            raise StaleRubric("rubric draft revision changed")
        if row.status == "processing":
            raise RepositoryConflict("rubric draft has an active operation")
        if row.status in {"confirmed", "published", "stale"}:
            raise RepositoryConflict("rubric draft is not editable")
        row.rubric_json = dict(rubric)
        row.status = "review_ready"
        row.pending_question_json = None
        row.last_error_json = None
        row.confirmed_by = None
        row.confirmed_at = None
        row.revision += 1
        _remember(row, command_id, digest)
        row.updated_at = timestamp
        session.flush()
        return _draft(row)


def confirm_rubric(
    rubric_id: str,
    *,
    expected_revision: int,
    source_question_revision: int,
    source_question_hash: str,
    command_id: str,
    digest: str,
    confirmed_by: str,
) -> RubricDraftRecord:
    timestamp = now()
    with session_scope() as session:
        row = session.get(RubricDraftRow, rubric_id)
        if row is None:
            raise KeyError(rubric_id)
        _current_question(session, row.question_draft_id, source_question_revision, source_question_hash)
        row = session.scalar(select(RubricDraftRow).where(RubricDraftRow.id == rubric_id).with_for_update())
        if row is None:
            raise KeyError(rubric_id)
        if _receipt(row, command_id, digest):
            return _draft(row)
        if row.source_question_revision != source_question_revision or row.source_question_hash != source_question_hash:
            raise StaleRubric("rubric source question changed")
        if row.revision != expected_revision:
            raise StaleRubric("rubric draft revision changed")
        if row.status != "review_ready" or not row.rubric_json:
            raise RepositoryConflict("rubric is not ready for teacher confirmation")
        row.status = "confirmed"
        row.confirmed_by = confirmed_by
        row.confirmed_at = timestamp
        row.revision += 1
        _remember(row, command_id, digest)
        row.updated_at = timestamp
        session.flush()
        return _draft(row)


def publish_rubric(
    rubric_id: str,
    *,
    expected_revision: int,
    source_question_revision: int,
    source_question_hash: str,
    command_id: str,
    digest: str,
    question_snapshot: dict[str, Any],
    bad_samples: list[dict[str, Any]],
    publication_status: str = "published",
    reference_answer_text: str,
    published_by: str,
    pass_threshold: int,
    contract_revision_id: str | None = None,
) -> tuple[RubricDraftRecord, QuestionRevisionRecord]:
    timestamp = now()
    with session_scope() as session:
        row = session.get(RubricDraftRow, rubric_id)
        if row is None:
            raise KeyError(rubric_id)
        _current_question(session, row.question_draft_id, source_question_revision, source_question_hash)
        row = session.scalar(select(RubricDraftRow).where(RubricDraftRow.id == rubric_id).with_for_update())
        if row is None:
            raise KeyError(rubric_id)
        receipt = (row.command_receipts_json or {}).get(command_id)
        if receipt is not None:
            if receipt.get("payload_hash") != digest:
                raise RepositoryConflict("rubric command payload conflicts")
            revision_id = receipt.get("revision_id")
            existing = session.get(BenchmarkQuestionRevisionRow, revision_id) if revision_id else None
            if existing is None:
                raise RepositoryConflict("published rubric receipt has no revision")
            return _draft(row), _revision(existing)
        if row.source_question_revision != source_question_revision or row.source_question_hash != source_question_hash:
            raise StaleRubric("rubric source question changed")
        if row.revision != expected_revision:
            raise StaleRubric("rubric draft revision changed")
        if row.status != "confirmed" or not row.rubric_json:
            raise RepositoryConflict("rubric must be explicitly confirmed before publishing")
        next_number = int(
            session.scalar(
                select(func.max(BenchmarkQuestionRevisionRow.revision_number)).where(
                    BenchmarkQuestionRevisionRow.question_draft_id == row.question_draft_id
                )
            )
            or 0
        ) + 1
        content = {
            "question": question_snapshot,
            "reference_answer_text": reference_answer_text,
            "rubric": row.rubric_json,
            "pass_threshold": pass_threshold,
            "source_question_revision": source_question_revision,
            "source_question_hash": source_question_hash,
            "contract_revision_id": contract_revision_id,
        }
        content_digest = payload_hash(content)
        existing = session.scalar(
            select(BenchmarkQuestionRevisionRow).where(
                BenchmarkQuestionRevisionRow.question_draft_id == row.question_draft_id,
                BenchmarkQuestionRevisionRow.content_sha256 == content_digest,
            )
        )
        if existing is not None:
            _remember_result(row, command_id, digest, {"revision_id": existing.id})
            row.status = "published"
            row.updated_at = timestamp
            session.flush()
            return _draft(row), _revision(existing)
        revision_row = BenchmarkQuestionRevisionRow(
            id=str(uuid4()),
            workspace_id=row.workspace_id,
            question_draft_id=row.question_draft_id,
            revision_number=next_number,
            source_question_revision=source_question_revision,
            source_question_hash=source_question_hash,
            contract_revision_id=contract_revision_id,
            question_snapshot_json=dict(question_snapshot),
            bad_samples_json=[dict(item) for item in bad_samples],
            reference_answer_text=reference_answer_text,
            rubric_json=dict(row.rubric_json),
            pass_threshold=pass_threshold,
            content_sha256=content_digest,
            publication_status=publication_status,
            published_by=published_by,
            published_at=timestamp,
            created_at=timestamp,
        )
        session.add(revision_row)
        row.status = "published"
        row.revision += 1
        _remember_result(row, command_id, digest, {"revision_id": revision_row.id})
        row.updated_at = timestamp
        try:
            session.flush()
        except IntegrityError:
            raise RepositoryConflict("rubric publication was updated concurrently") from None
        return _draft(row), _revision(revision_row)


def derive_draft(
    *,
    revision_id: str,
    workspace_id: str,
    source_question_revision: int,
    source_question_hash: str,
    command_id: str,
    digest: str,
) -> RubricDraftRecord:
    timestamp = now()
    with session_scope() as session:
        # The published snapshot is immutable; acquire the current question
        # lock first so derive and publish share the same lock order.
        source = session.get(BenchmarkQuestionRevisionRow, revision_id)
        if source is None:
            raise KeyError(revision_id)
        if source.workspace_id != workspace_id:
            raise RepositoryConflict("published question revision belongs to another workspace")
        _current_question(session, source.question_draft_id, source_question_revision, source_question_hash)
        row = session.scalar(
            select(RubricDraftRow)
            .where(RubricDraftRow.question_draft_id == source.question_draft_id)
            .with_for_update()
        )
        if row is None:
            raise KeyError(source.question_draft_id)
        if _receipt(row, command_id, digest):
            return _draft(row)
        if row.source_question_revision != source_question_revision or row.source_question_hash != source_question_hash:
            raise StaleRubric("current confirmed question changed")
        if row.status == "processing":
            raise RepositoryConflict("rubric draft has an active operation")
        row.rubric_json = dict(source.rubric_json)
        row.status = "review_ready"
        row.pending_question_json = None
        row.active_operation_id = None
        row.confirmed_by = None
        row.confirmed_at = None
        row.last_error_json = None
        row.revision += 1
        _remember(row, command_id, digest)
        row.updated_at = timestamp
        session.flush()
        return _draft(row)


def commit_worker_projection(
    rubric_id: str,
    *,
    expected_revision: int,
    operation_job_id: str,
    operation_attempt: int,
    worker_id: str,
    source_question_revision: int,
    source_question_hash: str,
    rubric: dict[str, Any],
    status: str = "review_ready",
    pending_question: dict[str, Any] | None = None,
) -> RubricDraftRecord:
    with session_scope() as session:
        operation = session.scalar(
            select(OperationJobRow).where(OperationJobRow.id == operation_job_id).with_for_update()
        )
        if (
            operation is None
            or operation.target_type != "rubric_draft"
            or operation.target_id != rubric_id
            or operation.business_revision != expected_revision
            or operation.kind not in {"rubric_process", "rubric_reproject"}
            or operation.status != "running"
            or operation.worker_id != worker_id
            or operation.attempts != operation_attempt
        ):
            raise StaleRubric("rubric operation attempt is stale")
        row = session.get(RubricDraftRow, rubric_id)
        if row is None:
            raise KeyError(rubric_id)
        _current_question(
            session,
            row.question_draft_id,
            source_question_revision,
            source_question_hash,
        )
        row = session.scalar(select(RubricDraftRow).where(RubricDraftRow.id == rubric_id).with_for_update())
        if row is None:
            raise KeyError(rubric_id)
        if row.revision != expected_revision:
            raise StaleRubric("rubric draft branch is stale")
        row.rubric_json = dict(rubric)
        row.status = status
        row.pending_question_json = dict(pending_question) if pending_question else None
        row.active_operation_id = None
        row.last_error_json = None
        row.revision += 1
        row.updated_at = now()
        session.flush()
        return _draft(row)


def mark_failed(
    rubric_id: str,
    code: str = "RUBRIC_PROCESS_FAILED",
    *,
    expected_revision: int | None = None,
    expected_operation_id: str | None = None,
    expected_operation_attempt: int | None = None,
    expected_worker_id: str | None = None,
) -> RubricDraftRecord:
    with session_scope() as session:
        row = session.scalar(
            select(RubricDraftRow).where(RubricDraftRow.id == rubric_id).with_for_update()
        )
        if row is None:
            raise KeyError(rubric_id)
        if expected_revision is not None and row.revision != expected_revision:
            return _draft(row)
        if expected_operation_id is not None and row.active_operation_id != expected_operation_id:
            return _draft(row)
        if expected_operation_id is not None:
            operation = session.get(OperationJobRow, expected_operation_id)
            if (
                operation is None
                or operation.status != "running"
                or (expected_operation_attempt is not None and operation.attempts != expected_operation_attempt)
                or (expected_worker_id is not None and operation.worker_id != expected_worker_id)
            ):
                return _draft(row)
        row.status = "failed"
        row.active_operation_id = None
        row.pending_question_json = None
        row.last_error_json = {"code": code}
        row.updated_at = now()
        session.flush()
        return _draft(row)


def mark_projection_pending(
    rubric_id: str,
    *,
    expected_revision: int | None = None,
    expected_operation_id: str | None = None,
) -> RubricDraftRecord:
    with session_scope() as session:
        row = session.scalar(
            select(RubricDraftRow).where(RubricDraftRow.id == rubric_id).with_for_update()
        )
        if row is None:
            raise KeyError(rubric_id)
        if expected_revision is not None and row.revision != expected_revision:
            return _draft(row)
        if expected_operation_id is not None and row.active_operation_id != expected_operation_id:
            return _draft(row)
        row.status = "projection_pending"
        row.active_operation_id = None
        row.pending_question_json = None
        row.updated_at = now()
        session.flush()
        return _draft(row)
