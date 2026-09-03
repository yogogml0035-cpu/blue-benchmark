import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Request, Response

from app.features.auth import repository
from app.features.auth.schemas import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    BootstrapResponse,
    LoginRequest,
    RegisterRequest,
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


def register(payload: RegisterRequest, response: Response) -> User:
    user = repository.UserRecord(
        id=str(uuid4()),
        username=payload.username,
        email=str(payload.email) if payload.email else None,
        password_hash=_hash_password(payload.password),
        password_generation=1,
        created_at=datetime.now(timezone.utc),
    )
    # The admin_slot unique constraint makes the single-admin rule atomic:
    # the first writer wins, any concurrent second registration is rejected.
    if not repository.add_first_user(user):
        raise AppError(409, "ADMIN_EXISTS", "平台只允许一个管理员账号。")
    _set_session(response, user)
    return to_user(user)


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


def bootstrap() -> BootstrapResponse:
    """Anonymous first-run probe.

    Reveals only whether the platform still accepts a first registration; it
    never exposes the admin's identity or any other enumerable fact.
    """

    return BootstrapResponse(registration_available=repository.count_users() == 0)


def assert_valid_password(password: str) -> None:
    """Shared length rule for register and the local password-reset CLI."""

    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        raise AppError(
            422,
            "PASSWORD_INVALID",
            f"密码长度必须在 {PASSWORD_MIN_LENGTH} 到 {PASSWORD_MAX_LENGTH} 个字符之间。",
        )


def reset_admin_password(new_password: str) -> None:
    """Local recovery path: replace the sole admin's password and revoke sessions.

    The password arrives via interactive hidden input, never through argv or
    environment variables. On success every existing session is revoked in the
    same transaction, so both the old password and all old sessions stop
    working immediately.
    """

    assert_valid_password(new_password)
    admin = repository.get_sole_admin()
    if admin is None:
        raise AppError(409, "ADMIN_MISSING", "平台还没有管理员，无法重置密码。")
    repository.reset_admin_password(admin.id, _hash_password(new_password))
