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
