"""Database access for scenes and scene upload credentials."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.lib.database import as_utc
from app.lib.database.models import (
    BatchUploadCommandRow,
    EvalQuestionRow,
    SceneCredentialRow,
    SceneRow,
)


def new_id() -> str:
    return str(uuid.uuid4())


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SceneRecord:
    id: str
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class SceneCredentialRecord:
    id: str
    scene_id: str
    label: str | None
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    revoked_reason: str | None


@dataclass(frozen=True)
class SceneSummary:
    scene: SceneRecord
    question_count: int
    active_credential_count: int


def _scene_record(row: SceneRow) -> SceneRecord:
    return SceneRecord(
        id=row.id,
        name=row.name,
        description=row.description,
        created_at=as_utc(row.created_at),
        updated_at=as_utc(row.updated_at),
    )


def _credential_record(row: SceneCredentialRow) -> SceneCredentialRecord:
    return SceneCredentialRecord(
        id=row.id,
        scene_id=row.scene_id,
        label=row.label,
        created_at=as_utc(row.created_at),
        last_used_at=as_utc(row.last_used_at) if row.last_used_at else None,
        revoked_at=as_utc(row.revoked_at) if row.revoked_at else None,
        revoked_reason=row.revoked_reason,
    )


def create_scene(session: Session, *, name: str, description: str | None, now: datetime) -> SceneRecord:
    row = SceneRow(id=new_id(), name=name, description=description, created_at=now, updated_at=now)
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ValueError("SCENE_NAME_EXISTS") from exc
    return _scene_record(row)


def get_scene(session: Session, scene_id: str) -> SceneRecord | None:
    row = session.get(SceneRow, scene_id)
    return _scene_record(row) if row else None


def list_scene_summaries(session: Session) -> list[SceneSummary]:
    scenes = session.execute(select(SceneRow).order_by(SceneRow.created_at)).scalars().all()
    question_counts = dict(
        session.execute(
            select(EvalQuestionRow.scene_id, func.count(EvalQuestionRow.id)).group_by(
                EvalQuestionRow.scene_id
            )
        ).all()
    )
    credential_counts = dict(
        session.execute(
            select(SceneCredentialRow.scene_id, func.count(SceneCredentialRow.id))
            .where(SceneCredentialRow.revoked_at.is_(None))
            .group_by(SceneCredentialRow.scene_id)
        ).all()
    )
    return [
        SceneSummary(
            scene=_scene_record(row),
            question_count=question_counts.get(row.id, 0),
            active_credential_count=credential_counts.get(row.id, 0),
        )
        for row in scenes
    ]


def create_credential(
    session: Session, *, scene_id: str, hashed: str, label: str | None, now: datetime
) -> SceneCredentialRecord:
    row = SceneCredentialRow(
        id=new_id(),
        scene_id=scene_id,
        token_hash=hashed,
        label=label,
        created_at=now,
    )
    session.add(row)
    session.flush()
    return _credential_record(row)


def get_credential_by_hash(session: Session, hashed: str) -> SceneCredentialRecord | None:
    row = session.execute(
        select(SceneCredentialRow).where(SceneCredentialRow.token_hash == hashed)
    ).scalar_one_or_none()
    return _credential_record(row) if row else None


def mark_credential_used(session: Session, credential_id: str, now: datetime) -> None:
    row = session.get(SceneCredentialRow, credential_id)
    if row:
        row.last_used_at = now


def list_credentials(session: Session, scene_id: str) -> list[SceneCredentialRecord]:
    rows = (
        session.execute(
            select(SceneCredentialRow)
            .where(SceneCredentialRow.scene_id == scene_id)
            .order_by(SceneCredentialRow.created_at)
        )
        .scalars()
        .all()
    )
    return [_credential_record(row) for row in rows]


def revoke_credential(
    session: Session, credential_id: str, *, reason: str, now: datetime
) -> SceneCredentialRecord | None:
    row = session.get(SceneCredentialRow, credential_id)
    if row is None or row.revoked_at is not None:
        return None
    row.revoked_at = now
    row.revoked_reason = reason
    session.flush()
    return _credential_record(row)


def revoke_scene_credentials(session: Session, scene_id: str, *, reason: str, now: datetime) -> int:
    rows = (
        session.execute(
            select(SceneCredentialRow)
            .where(SceneCredentialRow.scene_id == scene_id, SceneCredentialRow.revoked_at.is_(None))
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.revoked_at = now
        row.revoked_reason = reason
    session.flush()
    return len(rows)


def count_commands_for_scene(session: Session, scene_id: str) -> int:
    return session.execute(
        select(func.count(BatchUploadCommandRow.id)).where(
            BatchUploadCommandRow.scene_id == scene_id
        )
    ).scalar_one()


def count_questions_for_scene(session: Session, scene_id: str) -> int:
    return session.execute(
        select(func.count(EvalQuestionRow.id)).where(EvalQuestionRow.scene_id == scene_id)
    ).scalar_one()


def count_active_credentials(session: Session, scene_id: str) -> int:
    return session.execute(
        select(func.count(SceneCredentialRow.id)).where(
            SceneCredentialRow.scene_id == scene_id,
            SceneCredentialRow.revoked_at.is_(None),
        )
    ).scalar_one()
