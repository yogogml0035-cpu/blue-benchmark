"""Auth web contracts: env-seeded single admin, negative regressions, session gates."""

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.features.auth import service as auth_service
from app.lib.database import clear_business_data
from app.lib.settings import settings
from app.main import app
from scripts import admin_cli
from tests import helpers


def test_register_and_bootstrap_entries_are_gone() -> None:
    """Negative regression: the old first-run entries must not resolve."""

    clear_business_data()
    with TestClient(app) as client:
        assert client.get("/api/auth/bootstrap").status_code == 404
        response = client.post(
            "/api/auth/register",
            json={"username": "impostor", "password": "impostor-password"},
        )
        assert response.status_code == 404
        # The payload was not persisted through any side door.
        login = client.post(
            "/api/auth/login",
            json={"identifier": "impostor", "password": "impostor-password"},
        )
        assert login.status_code == 401


def test_startup_seeds_sole_admin_from_env() -> None:
    clear_business_data()
    # Entering the TestClient context runs the lifespan, which must seed the
    # admin from ADMIN_USERNAME / ADMIN_PASSWORD without any HTTP call.
    with TestClient(app):
        pass
    with TestClient(app) as client:
        user = helpers.login_admin(client)
        assert user["username"] == settings.admin_username
        assert client.get("/api/auth/me").status_code == 200


def test_missing_admin_env_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_business_data()
    monkeypatch.setattr(settings, "admin_username", "")
    with pytest.raises(RuntimeError) as excinfo:
        auth_service.ensure_admin_from_env()
    assert "ADMIN_USERNAME" in str(excinfo.value)

    monkeypatch.setattr(settings, "admin_username", "admin")
    # The settings validator strips env values, so a blank env arrives as "".
    monkeypatch.setattr(settings, "admin_password", SecretStr(""))
    with pytest.raises(RuntimeError) as excinfo:
        auth_service.ensure_admin_from_env()
    assert "ADMIN_PASSWORD" in str(excinfo.value)


def test_env_password_change_overwrites_and_revokes_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The environment is the sole authority: a restart applies the new password."""

    clear_business_data()
    with TestClient(app) as client:
        helpers.login_admin(client)

    old_session_client = TestClient(app)
    login = old_session_client.post(
        "/api/auth/login",
        json={
            "identifier": settings.admin_username,
            "password": settings.admin_password.get_secret_value(),
        },
    )
    assert login.status_code == 200
    assert old_session_client.get("/api/auth/me").status_code == 200

    old_password = settings.admin_password.get_secret_value()
    monkeypatch.setattr(settings, "admin_password", SecretStr("brand-new-password-1"))
    # Simulates the next API startup with the changed environment.
    auth_service.ensure_admin_from_env()

    # Old session is revoked; old password no longer works; new one does.
    assert old_session_client.get("/api/auth/me").status_code == 401
    with TestClient(app) as client:
        old_login = client.post(
            "/api/auth/login",
            json={"identifier": settings.admin_username, "password": old_password},
        )
        assert old_login.status_code == 401
        new_login = client.post(
            "/api/auth/login",
            json={"identifier": settings.admin_username, "password": "brand-new-password-1"},
        )
        assert new_login.status_code == 200


def test_unchanged_env_keeps_sessions_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Idempotent startup: matching credentials must not revoke live sessions."""

    clear_business_data()
    # Seed without a lifespan (bare TestClient): login must work right away.
    auth_service.ensure_admin_from_env()
    live_client = TestClient(app)
    login = live_client.post(
        "/api/auth/login",
        json={
            "identifier": settings.admin_username,
            "password": settings.admin_password.get_secret_value(),
        },
    )
    assert login.status_code == 200

    auth_service.ensure_admin_from_env()
    assert live_client.get("/api/auth/me").status_code == 200


def test_env_username_change_renames_without_revoking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_business_data()
    with TestClient(app):
        pass
    live_client = TestClient(app)
    login = live_client.post(
        "/api/auth/login",
        json={
            "identifier": settings.admin_username,
            "password": settings.admin_password.get_secret_value(),
        },
    )
    assert login.status_code == 200

    monkeypatch.setattr(settings, "admin_username", "renamed-admin")
    auth_service.ensure_admin_from_env()

    # Username-only change keeps the generation, so the live session survives.
    assert live_client.get("/api/auth/me").status_code == 200
    with TestClient(app) as client:
        renamed_login = client.post(
            "/api/auth/login",
            json={
                "identifier": "renamed-admin",
                "password": settings.admin_password.get_secret_value(),
            },
        )
        assert renamed_login.status_code == 200


def test_admin_cli_account_commands_are_gone() -> None:
    """Negative regression: the dual-authority password reset CLI is removed."""

    with pytest.raises(SystemExit) as excinfo:
        admin_cli.main(["account", "reset-password"])
    # argparse rejects the unknown command with exit code 2.
    assert excinfo.value.code == 2


def test_reset_generation_gate_blocks_raced_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A session created under the pre-change generation must stop resolving.

    This models the race where a login verifies the old password just before
    the env-driven overwrite commits and inserts its session just after the
    update's session sweep: the row survives, but the generation mismatch
    invalidates it.
    """

    from sqlalchemy import select

    from app.features.auth import repository as auth_repository
    from app.lib.database import session_scope
    from app.lib.database.models import UserRow

    clear_business_data()
    with TestClient(app) as client:
        helpers.login_admin(client)

    with session_scope() as session:
        user = session.scalars(select(UserRow)).first()
        assert user is not None
        user_id = user.id
        generation_before_reset = user.password_generation

    # The raced session is created with the generation observed before the change.
    auth_repository.create_session("raced-token", user_id, generation_before_reset)
    assert auth_repository.get_user_id_by_session("raced-token") == user_id

    monkeypatch.setattr(settings, "admin_password", SecretStr("post-reset-password-1"))
    auth_service.ensure_admin_from_env()

    # The raced session no longer resolves, even though code created it.
    assert auth_repository.get_user_id_by_session("raced-token") is None

    # A fresh login with the new password works and resolves normally.
    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"identifier": settings.admin_username, "password": "post-reset-password-1"},
        )
        assert login.status_code == 200
        assert client.get("/api/auth/me").status_code == 200


def test_generation_mismatch_lazily_deletes_stale_session() -> None:
    """A session row that survives an overwrite still fails the generation check.

    The update sweep deletes rows in the same transaction; this test covers the
    other half of the gate: a stale-generation row that is still present must
    stop resolving and be removed by the lazy cleanup branch.
    """

    from sqlalchemy import delete, select

    from app.features.auth import repository as auth_repository
    from app.lib.database import session_scope
    from app.lib.database.models import SessionRow, UserRow

    clear_business_data()
    with TestClient(app) as client:
        helpers.login_admin(client)

    with session_scope() as session:
        user = session.scalars(select(UserRow)).first()
        assert user is not None
        user_id = user.id
        # Drop existing sessions so only the session under test remains.
        session.execute(delete(SessionRow).where(SessionRow.user_id == user_id))

    # A session minted under generation 1...
    auth_repository.create_session("stale-token", user_id, 1)
    assert auth_repository.get_user_id_by_session("stale-token") == user_id

    # ...while the user's generation advances without sweeping sessions.
    with session_scope() as session:
        row = session.get(UserRow, user_id)
        assert row is not None
        row.password_generation = int(row.password_generation) + 1

    # Resolution fails and the stale row is removed by the lazy cleanup.
    assert auth_repository.get_user_id_by_session("stale-token") is None
    with session_scope() as session:
        remaining = session.execute(
            select(SessionRow).where(SessionRow.user_id == user_id)
        ).scalars().all()
    assert remaining == []
