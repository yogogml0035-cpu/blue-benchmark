from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib

from sqlalchemy import delete, select

from app.lib.database import as_utc, session_scope
from app.lib.database.models import SessionRow, UserRow

@dataclass(slots=True)
class UserRecord:
    id: str
    username: str
    email: str | None
    password_hash: str
    created_at: datetime


def _to_record(row: UserRow) -> UserRecord:
    return UserRecord(
        id=row.id,
        username=row.username,
        email=row.email,
        password_hash=row.password_hash,
        created_at=as_utc(row.created_at),
    )


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def find_by_username(username: str) -> UserRecord | None:
    normalized = username.casefold()
    with session_scope() as session:
        rows = session.scalars(select(UserRow)).all()
        row = next((item for item in rows if item.username.casefold() == normalized), None)
        return _to_record(row) if row else None


def find_by_email(email: str) -> UserRecord | None:
    normalized = email.casefold()
    with session_scope() as session:
        rows = session.scalars(select(UserRow)).all()
        row = next(
            (item for item in rows if item.email and item.email.casefold() == normalized),
            None,
        )
        return _to_record(row) if row else None


def add_first_user(user: UserRecord) -> bool:
    """Insert the single admin atomically.

    The ``admin_slot`` unique constraint rejects any concurrent second
    registration at the database level, so this returns False instead of
    persisting a second admin.
    """

    from sqlalchemy.exc import IntegrityError

    with session_scope() as session:
        session.add(
            UserRow(
                id=user.id,
                username=user.username,
                email=user.email,
                password_hash=user.password_hash,
                admin_slot="primary",
                created_at=user.created_at,
            )
        )
        try:
            session.flush()
            return True
        except IntegrityError:
            session.rollback()
            return False


def add_user(user: UserRecord) -> None:
    with session_scope() as session:
        session.add(
            UserRow(
                id=user.id,
                username=user.username,
                email=user.email,
                password_hash=user.password_hash,
                created_at=user.created_at,
            )
        )


def count_users() -> int:
    from sqlalchemy import func

    with session_scope() as session:
        return session.scalar(select(func.count(UserRow.id))) or 0


def get_user(user_id: str) -> UserRecord | None:
    with session_scope() as session:
        row = session.get(UserRow, user_id)
        return _to_record(row) if row else None


def create_session(token: str, user_id: str) -> None:
    with session_scope() as session:
        session.add(
            SessionRow(
                token_hash=_token_hash(token),
                user_id=user_id,
                created_at=datetime.now(timezone.utc),
            )
        )


def get_user_id_by_session(token: str | None) -> str | None:
    if not token:
        return None
    with session_scope() as session:
        row = session.get(SessionRow, _token_hash(token))
        return row.user_id if row else None


def revoke_session(token: str | None) -> None:
    if not token:
        return
    with session_scope() as session:
        session.execute(delete(SessionRow).where(SessionRow.token_hash == _token_hash(token)))


def reset() -> None:
    from app.lib.database import clear_business_data

    clear_business_data()
