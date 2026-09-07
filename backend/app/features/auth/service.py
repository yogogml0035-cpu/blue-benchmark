import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Request, Response

from app.features.auth import repository
from app.features.auth.schemas import (
    LoginRequest,
    User,
)
from app.lib.errors import AppError
from app.lib.settings import settings


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return f"{salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), 120_000
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def to_user(record: repository.UserRecord) -> User:
    return User(id=record.id, username=record.username, email=record.email, created_at=record.created_at)


def optional_current_user(request: Request) -> repository.UserRecord | None:
    token = request.cookies.get(settings.session_cookie_name)
    user_id = repository.get_user_id_by_session(token)
    return repository.get_user(user_id) if user_id else None


def require_current_user(request: Request) -> repository.UserRecord:
    user = optional_current_user(request)
    if not user:
        raise AppError(401, "AUTH_REQUIRED", "请先登录。")
    return user


def _set_session(response: Response, user: repository.UserRecord) -> None:
    token = secrets.token_urlsafe(32)
    repository.create_session(token, user.id, user.password_generation)
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        samesite="strict",
        secure=settings.session_cookie_secure,
        path="/",
    )


def ensure_admin_from_env() -> None:
    """Seed or sync the sole admin from ADMIN_USERNAME / ADMIN_PASSWORD.

    The environment is the only authority: on every API startup a missing
    account is created, and an existing one is overwritten whenever the
    configured username or password no longer matches. A password change bumps
    ``password_generation`` and revokes every session in the same transaction,
    so old cookies stop working immediately. When both values already match,
    this is a no-op write-wise (idempotent across restarts).
    """

    username = settings.admin_username
    password = settings.admin_password.get_secret_value()
    if not username or not password:
        missing = [
            name
            for name, value in (("ADMIN_USERNAME", username), ("ADMIN_PASSWORD", password))
            if not value
        ]
        raise RuntimeError(
            "admin account is not configured; set " + " and ".join(missing) + " in .env"
        )
    if len(password) > 128:
        raise RuntimeError("ADMIN_PASSWORD must be at most 128 characters")

    admin = repository.get_sole_admin()
    if admin is None:
        user = repository.UserRecord(
            id=str(uuid4()),
            username=username,
            email=None,
            password_hash=_hash_password(password),
            password_generation=1,
            created_at=datetime.now(timezone.utc),
        )
        # The admin_slot unique constraint keeps the single-admin rule atomic
        # even if two processes seed concurrently; the loser falls through to
        # the update path below.
        if repository.add_first_user(user):
            return
        admin = repository.get_sole_admin()
        if admin is None:  # pragma: no cover - defensive
            raise RuntimeError("admin seeding lost the insert race and found no admin row")

    username_changed = admin.username != username
    password_changed = not _verify_password(password, admin.password_hash)
    if not username_changed and not password_changed:
        return
    repository.update_admin_credentials(
        admin.id,
        username,
        _hash_password(password) if password_changed else admin.password_hash,
        bump_generation=password_changed,
    )


def login(payload: LoginRequest, response: Response) -> User:
    record = repository.find_by_username(payload.identifier) or repository.find_by_email(
        payload.identifier
    )
    if not record or not _verify_password(payload.password, record.password_hash):
        raise AppError(401, "INVALID_CREDENTIALS", "用户名或密码错误。")
    _set_session(response, record)
    return to_user(record)


def logout(request: Request, response: Response) -> None:
    # Require the caller to actually own a live session; an anonymous visitor
    # must not be able to force-logout the admin by replaying a cookie.
    require_current_user(request)
    repository.revoke_session(request.cookies.get(settings.session_cookie_name))
    response.delete_cookie(settings.session_cookie_name, path="/")
