from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select, update

from app.lib.database import as_utc, session_scope
from app.lib.database.models import EvidenceFileRow, FileDispositionRow, UploadBatchRow


@dataclass(frozen=True, slots=True)
class UploadBatchRecord:
    id: str
    workspace_id: str
    title: str
    task_description: str | None
    command_id: str | None
    status: str
    revision: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class EvidenceFileRecord:
    id: str
    upload_batch_id: str
    workspace_id: str
    storage_key: str
    original_name: str
    media_type: str
    size_bytes: int
    sha256: str
    parse_state: str
    parse_error: dict[str, Any] | None
    canonical_view: dict[str, Any] | None
    source_member: str | None
    created_at: datetime
    role: str = "unknown"
    required: bool = False
    ignored: bool = False
    visibility: str = "unconfirmed"
    rationale: str | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None


def _batch(row: UploadBatchRow) -> UploadBatchRecord:
    return UploadBatchRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        title=row.title,
        task_description=row.task_description,
        command_id=row.command_id,
        status=row.status,
        revision=row.revision,
        created_at=as_utc(row.created_at),
        updated_at=as_utc(row.updated_at),
    )


def _file(row: EvidenceFileRow, disposition: FileDispositionRow | None = None) -> EvidenceFileRecord:
    return EvidenceFileRecord(
        id=row.id,
        upload_batch_id=row.upload_batch_id,
        workspace_id=row.workspace_id,
        storage_key=row.storage_key,
        original_name=row.original_name,
        media_type=row.media_type,
        size_bytes=row.size_bytes,
        sha256=row.sha256,
        parse_state=row.parse_state,
        parse_error=row.parse_error_json,
        canonical_view=row.canonical_view_json,
        source_member=row.source_member,
        created_at=as_utc(row.created_at),
        role=disposition.role if disposition else "unknown",
        required=disposition.required if disposition else False,
        ignored=disposition.ignored if disposition else False,
        visibility=disposition.visibility if disposition else "unconfirmed",
        rationale=disposition.rationale if disposition else None,
        confirmed_by=disposition.confirmed_by if disposition else None,
        confirmed_at=as_utc(disposition.confirmed_at) if disposition and disposition.confirmed_at else None,
    )


def add_batch(batch: UploadBatchRecord, files: list[EvidenceFileRecord]) -> None:
    with session_scope() as session:
        session.add(
            UploadBatchRow(
                id=batch.id,
                workspace_id=batch.workspace_id,
                title=batch.title,
                task_description=batch.task_description,
                command_id=batch.command_id,
                status=batch.status,
                revision=batch.revision,
                created_at=batch.created_at,
                updated_at=batch.updated_at,
            )
        )
        session.flush()
        for item in files:
            session.add(
                EvidenceFileRow(
                    id=item.id,
                    upload_batch_id=item.upload_batch_id,
                    workspace_id=item.workspace_id,
                    storage_key=item.storage_key,
                    original_name=item.original_name,
                    media_type=item.media_type,
                    size_bytes=item.size_bytes,
                    sha256=item.sha256,
                    parse_state=item.parse_state,
                    parse_error_json=item.parse_error,
                    canonical_view_json=item.canonical_view,
                    source_member=item.source_member,
                    created_at=item.created_at,
                )
            )
        session.flush()
        for item in files:
            session.add(
                FileDispositionRow(
                    id=str(uuid4()),
                    evidence_file_id=item.id,
                    role="unknown",
                    required=False,
                    ignored=False,
                    visibility="unconfirmed",
                )
            )


def get_batch(batch_id: str) -> UploadBatchRecord | None:
    with session_scope() as session:
        row = session.get(UploadBatchRow, batch_id)
        return _batch(row) if row else None


def get_batch_by_command(workspace_id: str, command_id: str) -> UploadBatchRecord | None:
    with session_scope() as session:
        row = session.scalar(
            select(UploadBatchRow).where(
                UploadBatchRow.workspace_id == workspace_id,
                UploadBatchRow.command_id == command_id,
            )
        )
        return _batch(row) if row else None


def latest_batch(workspace_id: str) -> UploadBatchRecord | None:
    with session_scope() as session:
        row = session.scalar(
            select(UploadBatchRow)
            .where(UploadBatchRow.workspace_id == workspace_id)
            .order_by(UploadBatchRow.created_at.desc())
            .limit(1)
        )
        return _batch(row) if row else None


def list_files(batch_id: str) -> list[EvidenceFileRecord]:
    with session_scope() as session:
        rows = session.execute(
            select(EvidenceFileRow, FileDispositionRow)
            .outerjoin(FileDispositionRow, FileDispositionRow.evidence_file_id == EvidenceFileRow.id)
            .where(EvidenceFileRow.upload_batch_id == batch_id)
            .order_by(EvidenceFileRow.created_at, EvidenceFileRow.id)
        ).all()
        return [_file(row, disposition) for row, disposition in rows]


def get_file(file_id: str) -> EvidenceFileRecord | None:
    with session_scope() as session:
        result = session.execute(
            select(EvidenceFileRow, FileDispositionRow)
            .outerjoin(FileDispositionRow, FileDispositionRow.evidence_file_id == EvidenceFileRow.id)
            .where(EvidenceFileRow.id == file_id)
        ).first()
        return _file(result[0], result[1]) if result else None


def update_disposition(
    *,
    batch_id: str,
    file_id: str,
    role: str,
    required: bool,
    ignored: bool,
    visibility: str,
    rationale: str | None,
    confirmed_by: str,
    expected_revision: int,
) -> bool:
    with session_scope() as session:
        batch = session.get(UploadBatchRow, batch_id)
        file_row = session.get(EvidenceFileRow, file_id)
        disposition = session.scalar(
            select(FileDispositionRow).where(FileDispositionRow.evidence_file_id == file_id)
        )
        if (
            batch is None
            or file_row is None
            or disposition is None
            or file_row.upload_batch_id != batch_id
            or batch.revision != expected_revision
        ):
            return False
        disposition.role = role
        disposition.required = required
        disposition.ignored = ignored
        disposition.visibility = visibility
        disposition.rationale = rationale
        disposition.confirmed_by = confirmed_by
        disposition.confirmed_at = datetime.now(timezone.utc)
        batch.revision += 1
        batch.updated_at = datetime.now(timezone.utc)
        session.flush()
        return True


def delete_batch(batch_id: str) -> None:
    with session_scope() as session:
        session.execute(delete(UploadBatchRow).where(UploadBatchRow.id == batch_id))


def update_status(
    batch_id: str,
    status: str,
    *,
    expected_revision: int | None = None,
    bump_revision: bool = False,
) -> bool:
    with session_scope() as session:
        values: dict[str, Any] = {"status": status}
        if bump_revision:
            values["revision"] = UploadBatchRow.revision + 1
        values["updated_at"] = datetime.now(timezone.utc)
        statement = update(UploadBatchRow).where(UploadBatchRow.id == batch_id)
        if expected_revision is not None:
            statement = statement.where(UploadBatchRow.revision == expected_revision)
        result = session.execute(statement.values(**values))
        return result.rowcount == 1
