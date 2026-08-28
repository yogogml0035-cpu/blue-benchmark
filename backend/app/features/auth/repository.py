from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class UserRecord:
    id: str
    username: str
    email: str | None
    password_hash: str
    created_at: datetime


users: dict[str, UserRecord] = {}
sessions: dict[str, str] = {}


def find_by_username(username: str) -> UserRecord | None:
    normalized = username.casefold()
    return next((user for user in users.values() if user.username.casefold() == normalized), None)


def find_by_email(email: str) -> UserRecord | None:
    normalized = email.casefold()
    return next(
        (user for user in users.values() if user.email and user.email.casefold() == normalized),
        None,
    )


def add_user(user: UserRecord) -> None:
    users[user.id] = user


def get_user(user_id: str) -> UserRecord | None:
    return users.get(user_id)


def create_session(token: str, user_id: str) -> None:
    sessions[token] = user_id


def get_user_id_by_session(token: str | None) -> str | None:
    return sessions.get(token) if token else None


def revoke_session(token: str | None) -> None:
    if token:
        sessions.pop(token, None)


def reset() -> None:
    users.clear()
    sessions.clear()

