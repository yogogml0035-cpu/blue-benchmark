"""Auth web contracts: anonymous bootstrap probe and local password reset."""

import getpass

import pytest
from fastapi.testclient import TestClient

from app.lib.database import clear_business_data
from app.main import app
from scripts import admin_cli
from tests import helpers


def test_bootstrap_reports_registration_availability_only() -> None:
    clear_business_data()
    with TestClient(app) as client:
        # Empty platform: registration is open, anonymously.
        probe = client.get("/api/auth/bootstrap")
        assert probe.status_code == 200
        body = probe.json()
        assert body == {"registration_available": True}

        helpers.register_admin(client, username="the-admin")

        probe = client.get("/api/auth/bootstrap")
        assert probe.status_code == 200
        # Only the boolean is exposed: no username, email, id or any hint.
        assert probe.json() == {"registration_available": False}
        assert "the-admin" not in probe.text


def test_password_reset_invalidates_old_password_and_sessions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client, username="reset-admin")
        # An authenticated session exists before the reset.
        assert client.get("/api/auth/me").status_code == 200

    old_session_client = TestClient(app)
    login = old_session_client.post(
        "/api/auth/login",
        json={"identifier": "reset-admin", "password": "platform-admin-password"},
    )
    assert login.status_code == 200
    assert old_session_client.get("/api/auth/me").status_code == 200

    answers = iter(["brand-new-password-1", "brand-new-password-1"])
    monkeypatch.setattr(getpass, "getpass", lambda *_a, **_k: next(answers))
    exit_code = admin_cli.main(["account", "reset-password"])
    assert exit_code == 0

    captured = capsys.readouterr()
    # The password must never appear in CLI output.
    assert "brand-new-password-1" not in captured.out
    assert "brand-new-password-1" not in captured.err

    # Old session is revoked; old password no longer works.
    assert old_session_client.get("/api/auth/me").status_code == 401
    with TestClient(app) as client:
        old_login = client.post(
            "/api/auth/login",
            json={"identifier": "reset-admin", "password": "platform-admin-password"},
        )
        assert old_login.status_code == 401
        new_login = client.post(
            "/api/auth/login",
            json={"identifier": "reset-admin", "password": "brand-new-password-1"},
        )
        assert new_login.status_code == 200


def test_password_reset_mismatched_inputs_change_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client, username="mismatch-admin")

    answers = iter(["candidate-password-1", "different-password-2"])
    monkeypatch.setattr(getpass, "getpass", lambda *_a, **_k: next(answers))
    with pytest.raises(SystemExit):
        admin_cli.main(["account", "reset-password"])

    captured = capsys.readouterr()
    assert "candidate-password-1" not in captured.out + captured.err
    assert "different-password-2" not in captured.out + captured.err

    # The original password still works.
    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"identifier": "mismatch-admin", "password": "platform-admin-password"},
        )
        assert login.status_code == 200


def test_password_reset_rejects_invalid_length(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client, username="short-admin")

    answers = iter(["short", "short"])
    monkeypatch.setattr(getpass, "getpass", lambda *_a, **_k: next(answers))
    with pytest.raises(SystemExit):
        admin_cli.main(["account", "reset-password"])

    captured = capsys.readouterr()
    assert "short" not in captured.out

    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"identifier": "short-admin", "password": "platform-admin-password"},
        )
        assert login.status_code == 200


def test_password_reset_without_admin_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clear_business_data()
    answers = iter(["whatever-password-1", "whatever-password-1"])
    monkeypatch.setattr(getpass, "getpass", lambda *_a, **_k: next(answers))
    with pytest.raises(SystemExit):
        admin_cli.main(["account", "reset-password"])
    captured = capsys.readouterr()
    assert "whatever-password-1" not in captured.out + captured.err


def test_reset_generation_gate_blocks_raced_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A session created under the pre-reset generation must stop resolving.

    This models the race where a login verifies the old password just before
    the reset commits and inserts its session just after the reset's session
    sweep: the row survives, but the generation mismatch invalidates it.
    """

    from sqlalchemy import select

    from app.features.auth import repository as auth_repository
    from app.features.auth import service as auth_service
    from app.lib.database import session_scope
    from app.lib.database.models import UserRow

    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client, username="raced-admin")

    with session_scope() as session:
        user = session.scalars(select(UserRow)).first()
        assert user is not None
        user_id = user.id
        generation_before_reset = user.password_generation

    # The raced session is created with the generation observed before reset.
    auth_repository.create_session("raced-token", user_id, generation_before_reset)
    assert auth_repository.get_user_id_by_session("raced-token") == user_id

    answers = iter(["post-reset-password-1", "post-reset-password-1"])
    monkeypatch.setattr(getpass, "getpass", lambda *_a, **_k: next(answers))
    assert admin_cli.main(["account", "reset-password"]) == 0

    # The raced session no longer resolves, even though code created it.
    assert auth_repository.get_user_id_by_session("raced-token") is None

    # A fresh login with the new password works and resolves normally.
    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"identifier": "raced-admin", "password": "post-reset-password-1"},
        )
        assert login.status_code == 200
        assert client.get("/api/auth/me").status_code == 200


def test_generation_mismatch_lazily_deletes_stale_session() -> None:
    """A session row that survives a reset still fails the generation check.

    The reset sweep deletes rows in the same transaction; this test covers the
    other half of the gate: a stale-generation row that is still present must
    stop resolving and be removed by the lazy cleanup branch.
    """

    from sqlalchemy import delete, select

    from app.features.auth import repository as auth_repository
    from app.lib.database import session_scope
    from app.lib.database.models import SessionRow, UserRow

    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client, username="stale-admin")

    with session_scope() as session:
        user = session.scalars(select(UserRow)).first()
        assert user is not None
        user_id = user.id
        # Drop the registration session so only the session under test remains.
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
