from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import secrets
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.lib.database import as_utc, session_scope
from app.lib.database.models import (
    AuthoringConnectionRow,
    AuthoringExternalCommandRow,
    UserRow,
    WorkspaceRow,
)


SCOPES = ["connection:read", "draft:create"]


@dataclass(frozen=True, slots=True)
class ConnectionRecord:
    id: str
    workspace_id: str
    user_id: str
    client_name: str
    scopes: list[str]
    code_expires_at: datetime | None
    code_used_at: datetime | None
    token_created_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    revoked_reason: str | None
    active_request_count: int
    last_request_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ExternalCommandRecord:
    id: str
    connection_id: str
    command_id: str
    payload_hash: str
    status: str
    conversation_id: str | None
    draft_id: str | None
    created_at: datetime
    completed_at: datetime | None


class ConnectionBusy(RuntimeError):
    pass


class ConnectionRateLimited(RuntimeError):
    pass


class ConnectionInvalid(RuntimeError):
    pass


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _connection(row: AuthoringConnectionRow) -> ConnectionRecord:
    return ConnectionRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        user_id=row.user_id,
        client_name=row.client_name,
        scopes=list(row.scope_json or []),
        code_expires_at=as_utc(row.code_expires_at) if row.code_expires_at else None,
        code_used_at=as_utc(row.code_used_at) if row.code_used_at else None,
        token_created_at=as_utc(row.token_created_at) if row.token_created_at else None,
        last_used_at=as_utc(row.last_used_at) if row.last_used_at else None,
        revoked_at=as_utc(row.revoked_at) if row.revoked_at else None,
        revoked_reason=row.revoked_reason,
        active_request_count=int(row.active_request_count or 0),
        last_request_at=as_utc(row.last_request_at) if row.last_request_at else None,
        created_at=as_utc(row.created_at),
        updated_at=as_utc(row.updated_at),
    )


def _command(row: AuthoringExternalCommandRow) -> ExternalCommandRecord:
    return ExternalCommandRecord(
        id=row.id,
        connection_id=row.connection_id,
        command_id=row.command_id,
        payload_hash=row.payload_hash,
        status=row.status,
        conversation_id=row.conversation_id,
        draft_id=row.draft_id,
        created_at=as_utc(row.created_at),
        completed_at=as_utc(row.completed_at) if row.completed_at else None,
    )


def create_connection(*, workspace_id: str, user_id: str, client_name: str, expires_at: datetime) -> tuple[ConnectionRecord, str]:
    now = datetime.now(timezone.utc)
    code = secrets.token_urlsafe(32)
    with session_scope() as session:
        active = session.scalars(
            select(AuthoringConnectionRow)
            .where(AuthoringConnectionRow.workspace_id == workspace_id, AuthoringConnectionRow.revoked_at.is_(None))
            .with_for_update()
        ).all()
        for row in active:
            row.revoked_at = now
            row.revoked_reason = "rebound"
            row.updated_at = now
        row = AuthoringConnectionRow(
            id=str(uuid4()),
            workspace_id=workspace_id,
            user_id=user_id,
            client_name=client_name,
            scope_json=list(SCOPES),
            code_hash=_hash(code),
            code_expires_at=expires_at,
            code_used_at=None,
            token_hash=None,
            token_created_at=None,
            last_used_at=None,
            revoked_at=None,
            revoked_reason=None,
            active_request_count=0,
            last_request_at=None,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()
        return _connection(row), code


def get_for_workspace(workspace_id: str, connection_id: str | None = None) -> ConnectionRecord | None:
    with session_scope() as session:
        statement = select(AuthoringConnectionRow).where(AuthoringConnectionRow.workspace_id == workspace_id)
        if connection_id:
            statement = statement.where(AuthoringConnectionRow.id == connection_id)
        else:
            statement = statement.where(AuthoringConnectionRow.revoked_at.is_(None)).order_by(AuthoringConnectionRow.created_at.desc())
        row = session.scalar(statement)
        return _connection(row) if row else None


def revoke(*, workspace_id: str, connection_id: str, reason: str) -> ConnectionRecord:
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        row = session.scalar(
            select(AuthoringConnectionRow)
            .where(AuthoringConnectionRow.workspace_id == workspace_id, AuthoringConnectionRow.id == connection_id)
            .with_for_update()
        )
        if row is None:
            raise KeyError(connection_id)
        if row.revoked_at is None:
            row.revoked_at = now
            row.revoked_reason = reason
            row.updated_at = now
        session.flush()
        return _connection(row)


def exchange(code: str) -> tuple[ConnectionRecord, str]:
    now = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(48)
    with session_scope() as session:
        row = session.scalar(
            select(AuthoringConnectionRow)
            .where(AuthoringConnectionRow.code_hash == _hash(code))
            .with_for_update()
        )
        if row is None or row.revoked_at is not None:
            raise ConnectionInvalid("connection code is invalid")
        if row.code_used_at is not None:
            raise ConnectionInvalid("connection code was already exchanged")
        if row.code_expires_at is None or as_utc(row.code_expires_at) <= now:
            raise ConnectionInvalid("connection code expired")
        if session.get(UserRow, row.user_id) is None or session.get(WorkspaceRow, row.workspace_id) is None:
            raise ConnectionInvalid("connection is no longer available")
        row.code_used_at = now
        row.token_hash = _hash(token)
        row.token_created_at = now
        row.last_used_at = now
        row.updated_at = now
        session.flush()
        return _connection(row), token


def authenticate_token(token: str) -> ConnectionRecord:
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        row = session.scalar(
            select(AuthoringConnectionRow).where(AuthoringConnectionRow.token_hash == _hash(token)).with_for_update()
        )
        if row is None or row.revoked_at is not None:
            raise ConnectionInvalid("token is invalid")
        if session.get(UserRow, row.user_id) is None or session.get(WorkspaceRow, row.workspace_id) is None:
            raise ConnectionInvalid("connection is no longer available")
        if not hmac.compare_digest(row.token_hash or "", _hash(token)):
            raise ConnectionInvalid("token is invalid")
        row.last_used_at = now
        row.updated_at = now
        session.flush()
        return _connection(row)


def begin_request(
    connection_id: str,
    *,
    max_concurrent: int,
    min_interval_seconds: float,
    lease_seconds: int,
) -> None:
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        row = session.scalar(select(AuthoringConnectionRow).where(AuthoringConnectionRow.id == connection_id).with_for_update())
        if row is None or row.revoked_at is not None or row.token_hash is None:
            raise ConnectionInvalid("connection is invalid")
        active_count = int(row.active_request_count or 0)
        if active_count and row.last_request_at is not None:
            elapsed = (now - as_utc(row.last_request_at)).total_seconds()
            if elapsed >= lease_seconds:
                # A crashed process cannot run the finally block. The
                # synchronous payload path is bounded, so an old count is a
                # stale lease and must not permanently deny future uploads.
                row.active_request_count = 0
                active_count = 0
        if active_count >= max_concurrent:
            raise ConnectionBusy("external request concurrency limit reached")
        if row.last_request_at is not None:
            elapsed = (now - as_utc(row.last_request_at)).total_seconds()
            if elapsed < min_interval_seconds:
                raise ConnectionRateLimited("external request rate limit reached")
        row.active_request_count = active_count + 1
        row.last_request_at = now
        row.updated_at = now


def finish_request(connection_id: str) -> None:
    with session_scope() as session:
        row = session.scalar(select(AuthoringConnectionRow).where(AuthoringConnectionRow.id == connection_id).with_for_update())
        if row is None:
            return
        row.active_request_count = max(0, int(row.active_request_count or 0) - 1)
        row.updated_at = datetime.now(timezone.utc)


def get_command(connection_id: str, command_id: str) -> ExternalCommandRecord | None:
    with session_scope() as session:
        row = session.scalar(
            select(AuthoringExternalCommandRow).where(
                AuthoringExternalCommandRow.connection_id == connection_id,
                AuthoringExternalCommandRow.command_id == command_id,
            )
        )
        return _command(row) if row else None


def reserve_command(connection_id: str, command_id: str, payload_hash: str) -> tuple[ExternalCommandRecord, bool]:
    now = datetime.now(timezone.utc)
    try:
        with session_scope() as session:
            row = AuthoringExternalCommandRow(
                id=str(uuid4()),
                connection_id=connection_id,
                command_id=command_id,
                payload_hash=payload_hash,
                status="creating",
                conversation_id=None,
                draft_id=None,
                created_at=now,
                completed_at=None,
            )
            session.add(row)
            session.flush()
            return _command(row), True
    except IntegrityError:
        existing = get_command(connection_id, command_id)
        if existing is None:
            raise
        return existing, False


def release_command(connection_id: str, command_id: str) -> None:
    with session_scope() as session:
        session.execute(
            delete(AuthoringExternalCommandRow).where(
                AuthoringExternalCommandRow.connection_id == connection_id,
                AuthoringExternalCommandRow.command_id == command_id,
                AuthoringExternalCommandRow.status == "creating",
            )
        )
