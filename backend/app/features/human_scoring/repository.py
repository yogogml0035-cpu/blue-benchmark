"""Persistence boundary for external submissions and immutable human scores."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.lib.database import as_utc, session_scope
from app.lib.database.models import (
    EvaluationSubmissionRow,
    HumanScoreItemRow,
    HumanScoreRow,
)


class RepositoryConflict(RuntimeError):
    """A command was reused with a different payload or a write raced."""


class ScoreParentConflict(RepositoryConflict):
    """Another immutable score already claimed this parent score."""


@dataclass(frozen=True, slots=True)
class SubmissionRecord:
    id: str
    workspace_id: str
    question_revision_id: str
    content_storage_key: str
    source: str
    original_name: str | None
    media_type: str
    size_bytes: int
    sha256: str
    command_id: str
    payload_hash: str
    submitted_by: str
    submitted_at: datetime


@dataclass(frozen=True, slots=True)
class ScoreItemRecord:
    id: str
    score_id: str
    criterion_id: str
    score: int
    reason: str | None
    hard_fail_triggered: bool | None
    critical_passed: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ScoreRecord:
    id: str
    submission_id: str
    question_revision_id: str
    parent_score_id: str | None
    status: str
    total_score: int
    critical_passed: bool
    passed: bool
    overall_reason: str | None
    command_id: str
    payload_hash: str
    scored_by: str
    submitted_at: datetime
    items: tuple[ScoreItemRecord, ...]


def now() -> datetime:
    return datetime.now(timezone.utc)


def payload_hash(value: Any) -> str:
    """Hash command metadata without ever requiring the answer body."""

    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _submission(row: EvaluationSubmissionRow) -> SubmissionRecord:
    return SubmissionRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        question_revision_id=row.question_revision_id,
        content_storage_key=row.content_storage_key,
        source=row.source,
        original_name=row.original_name,
        media_type=row.media_type,
        size_bytes=row.size_bytes,
        sha256=row.sha256,
        command_id=row.command_id,
        payload_hash=row.payload_hash,
        submitted_by=row.submitted_by,
        submitted_at=as_utc(row.submitted_at),
    )


def _item(row: HumanScoreItemRow) -> ScoreItemRecord:
    return ScoreItemRecord(
        id=row.id,
        score_id=row.score_id,
        criterion_id=row.criterion_id,
        score=row.score,
        reason=row.reason,
        hard_fail_triggered=row.hard_fail_triggered,
        critical_passed=row.critical_passed,
        created_at=as_utc(row.created_at),
    )


def _score(row: HumanScoreRow, items: list[HumanScoreItemRow]) -> ScoreRecord:
    return ScoreRecord(
        id=row.id,
        submission_id=row.submission_id,
        question_revision_id=row.question_revision_id,
        parent_score_id=row.parent_score_id,
        status=row.status,
        total_score=row.total_score,
        critical_passed=row.critical_passed,
        passed=row.passed,
        overall_reason=row.overall_reason,
        command_id=row.command_id,
        payload_hash=row.payload_hash,
        scored_by=row.scored_by,
        submitted_at=as_utc(row.submitted_at),
        items=tuple(_item(item) for item in items),
    )


def _items_for_score(session, score_id: str) -> list[HumanScoreItemRow]:
    return list(
        session.scalars(
            select(HumanScoreItemRow)
            .where(HumanScoreItemRow.score_id == score_id)
            .order_by(HumanScoreItemRow.created_at, HumanScoreItemRow.criterion_id)
        ).all()
    )


def get_submission(submission_id: str) -> SubmissionRecord | None:
    with session_scope() as session:
        row = session.get(EvaluationSubmissionRow, submission_id)
        return _submission(row) if row else None


def get_submission_by_command(workspace_id: str, command_id: str) -> SubmissionRecord | None:
    with session_scope() as session:
        row = session.scalar(
            select(EvaluationSubmissionRow).where(
                EvaluationSubmissionRow.workspace_id == workspace_id,
                EvaluationSubmissionRow.command_id == command_id,
            )
        )
        return _submission(row) if row else None


def list_submission_ids() -> set[str]:
    """Return only identifiers needed by startup storage reconciliation."""

    with session_scope() as session:
        return set(session.scalars(select(EvaluationSubmissionRow.id)).all())


def add_submission(record: SubmissionRecord) -> tuple[SubmissionRecord, bool]:
    """Insert once; a unique-command race returns the winner for idempotency."""

    try:
        with session_scope() as session:
            session.add(
                EvaluationSubmissionRow(
                    id=record.id,
                    workspace_id=record.workspace_id,
                    question_revision_id=record.question_revision_id,
                    content_storage_key=record.content_storage_key,
                    source=record.source,
                    original_name=record.original_name,
                    media_type=record.media_type,
                    size_bytes=record.size_bytes,
                    sha256=record.sha256,
                    command_id=record.command_id,
                    payload_hash=record.payload_hash,
                    submitted_by=record.submitted_by,
                    submitted_at=record.submitted_at,
                )
            )
            session.flush()
            return record, False
    except IntegrityError:
        existing = get_submission_by_command(record.workspace_id, record.command_id)
        if existing is not None:
            if existing.payload_hash != record.payload_hash:
                raise RepositoryConflict("submission command payload conflicts") from None
            return existing, True
        raise


def get_score(score_id: str) -> ScoreRecord | None:
    with session_scope() as session:
        row = session.get(HumanScoreRow, score_id)
        if row is None:
            return None
        return _score(row, _items_for_score(session, row.id))


def get_score_by_command(submission_id: str, command_id: str) -> ScoreRecord | None:
    with session_scope() as session:
        row = session.scalar(
            select(HumanScoreRow).where(
                HumanScoreRow.submission_id == submission_id,
                HumanScoreRow.command_id == command_id,
            )
        )
        if row is None:
            return None
        return _score(row, _items_for_score(session, row.id))


def list_scores(submission_id: str) -> list[ScoreRecord]:
    with session_scope() as session:
        rows = session.scalars(
            select(HumanScoreRow)
            .where(HumanScoreRow.submission_id == submission_id)
            .order_by(HumanScoreRow.submitted_at, HumanScoreRow.id)
        ).all()
        return [_score(row, _items_for_score(session, row.id)) for row in rows]


def add_score(
    *,
    submission_id: str,
    question_revision_id: str,
    parent_score_id: str | None,
    total_score: int,
    critical_passed: bool,
    passed: bool,
    overall_reason: str | None,
    command_id: str,
    digest: str,
    scored_by: str,
    submitted_at: datetime,
    items: list[dict[str, Any]],
) -> tuple[ScoreRecord, bool]:
    """Append a submitted score and its items in one database transaction."""

    score_id = str(uuid4())
    try:
        with session_scope() as session:
            row = HumanScoreRow(
                id=score_id,
                submission_id=submission_id,
                question_revision_id=question_revision_id,
                parent_score_id=parent_score_id,
                status="submitted",
                total_score=total_score,
                critical_passed=critical_passed,
                passed=passed,
                overall_reason=overall_reason,
                command_id=command_id,
                payload_hash=digest,
                scored_by=scored_by,
                submitted_at=submitted_at,
            )
            session.add(row)
            session.flush()
            item_rows: list[HumanScoreItemRow] = []
            for item in items:
                item_row = HumanScoreItemRow(
                    id=str(uuid4()),
                    score_id=score_id,
                    criterion_id=str(item["criterion_id"]),
                    score=int(item["score"]),
                    reason=item.get("reason"),
                    hard_fail_triggered=item.get("hard_fail_triggered"),
                    critical_passed=bool(item["critical_passed"]),
                    created_at=submitted_at,
                )
                session.add(item_row)
                item_rows.append(item_row)
            session.flush()
            return _score(row, item_rows), False
    except IntegrityError:
        existing = get_score_by_command(submission_id, command_id)
        if existing is not None:
            if existing.payload_hash != digest:
                raise RepositoryConflict("score command payload conflicts") from None
            return existing, True
        if parent_score_id is not None:
            with session_scope() as session:
                claimed = session.scalar(
                    select(HumanScoreRow).where(
                        HumanScoreRow.submission_id == submission_id,
                        HumanScoreRow.parent_score_id == parent_score_id,
                    )
                )
            if claimed is not None:
                raise ScoreParentConflict("score parent was already claimed") from None
        raise
