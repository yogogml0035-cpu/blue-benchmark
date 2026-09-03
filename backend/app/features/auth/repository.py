from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib

from sqlalchemy import delete, select

from app.lib.database import as_utc, engine, session_scope
from app.lib.database.models import SessionRow, UserRow

@dataclass(slots=True)
class UserRecord:
    id: str
    username: str
    email: str | None
    password_hash: str
    password_generation: int
    created_at: datetime


def _to_record(row: UserRow) -> UserRecord:
    return UserRecord(
        id=row.id,
        username=row.username,
        email=row.email,
        password_hash=row.password_hash,
        password_generation=int(row.password_generation),
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
                password_generation=user.password_generation,
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
                password_generation=user.password_generation,
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


def create_session(token: str, user_id: str, password_generation: int) -> None:
    with session_scope() as session:
        session.add(
            SessionRow(
                token_hash=_token_hash(token),
                user_id=user_id,
                password_generation=password_generation,
                created_at=datetime.now(timezone.utc),
            )
        )


def get_user_id_by_session(token: str | None) -> str | None:
    """Resolve a session token, enforcing the password-generation gate.

    A session is only valid while it carries the generation that was current
    when it was created; a password reset bumps the user's generation, which
    invalidates every pre-existing session even if its row survived the reset
    transaction (for example, a concurrent login that committed after the
    reset's session sweep).
    """

    if not token:
        return None
    with session_scope() as session:
        row = session.execute(
            select(SessionRow, UserRow)
            .join(UserRow, UserRow.id == SessionRow.user_id)
            .where(SessionRow.token_hash == _token_hash(token))
        ).first()
        if row is None:
            return None
        session_row, user_row = row
        if session_row.password_generation != user_row.password_generation:
            # Delete the stale row on a dedicated connection: the surrounding
            # transaction may later roll back (for example when a dependency
            # raises 401/404 after resolution), and the cleanup must survive.
            stale_hash = session_row.token_hash
            session.rollback()
            with engine.begin() as connection:
                connection.execute(
                    delete(SessionRow).where(SessionRow.token_hash == stale_hash)
                )
            return None
        return user_row.id


def revoke_session(token: str | None) -> None:
    if not token:
        return
    with session_scope() as session:
        session.execute(delete(SessionRow).where(SessionRow.token_hash == _token_hash(token)))


def get_sole_admin() -> UserRecord | None:
    """Return the single admin user, or None when the platform is empty."""

    with session_scope() as session:
        rows = session.scalars(select(UserRow).order_by(UserRow.created_at)).all()
        return _to_record(rows[0]) if rows else None


def reset_admin_password(user_id: str, password_hash: str) -> None:
    """Overwrite the admin password and revoke every session atomically.

    Bumping ``password_generation`` in the same transaction is the durable
    half of the revocation: any session created under the old generation
    (including one racing this reset) stops resolving, while the DELETE
    sweeps the rows that already exist.
    """

    with session_scope() as session:
        row = session.get(UserRow, user_id)
        if row is None:
            raise LookupError("admin user missing")
        row.password_hash = password_hash
        row.password_generation = int(row.password_generation) + 1
        session.execute(delete(SessionRow).where(SessionRow.user_id == user_id))


def reset() -> None:
    from app.lib.database import clear_business_data

    clear_business_data()
