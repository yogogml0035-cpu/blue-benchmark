"""Scene administration: folders, credentials, single-admin guard."""

from fastapi.testclient import TestClient

from app.lib.database import clear_business_data
from app.main import app
from tests import helpers


def test_single_admin_guard_blocks_second_registration() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client, username="first-admin")
    # A separate unauthenticated client must be blocked by the single-admin rule.
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/register",
            json={"username": "second-admin", "password": "another-password-1"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ADMIN_EXISTS"


def test_scene_requires_admin_session() -> None:
    clear_business_data()
    with TestClient(app) as client:
        response = client.post("/api/scenes", json={"name": "场景A"})
        assert response.status_code == 401
        response = client.get("/api/scenes")
        assert response.status_code == 401


def test_scene_lifecycle_and_credential_plaintext_rules() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client)
        scene = helpers.create_scene(client, name="媒体场景")

        # Duplicate names conflict.
        duplicate = client.post("/api/scenes", json={"name": "媒体场景"})
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "SCENE_NAME_EXISTS"

        issued = helpers.issue_credential(client, scene["id"], label="首次凭证")
        assert issued["token"].startswith("sep_")
        plaintext = issued["token"]

        # Status views never return plaintext tokens.
        status = client.get(f"/api/scenes/{scene['id']}")
        assert status.status_code == 200
        body = status.json()
        assert plaintext not in status.text
        assert body["scene"]["active_credential_count"] == 1
        assert body["credentials"][0]["status"] == "active"
        assert "token" not in body["credentials"][0]

        # Rotate revokes every active credential and shows plaintext once.
        rotated = client.post(
            f"/api/scenes/{scene['id']}/credentials/rotation", json={"label": "轮换"}
        )
        assert rotated.status_code == 201
        new_token = rotated.json()["token"]
        assert new_token != plaintext

        status = client.get(f"/api/scenes/{scene['id']}")
        credentials = status.json()["credentials"]
        assert len(credentials) == 2
        revoked = [item for item in credentials if item["status"] == "revoked"]
        assert len(revoked) == 1
        assert revoked[0]["revoked_reason"] == "rotated"

        # Manual revoke is idempotency-safe: second revoke conflicts.
        active_id = next(
            item["credential_id"] for item in credentials if item["status"] == "active"
        )
        revoke = client.delete(f"/api/scenes/{scene['id']}/credentials/{active_id}")
        assert revoke.status_code == 200
        again = client.delete(f"/api/scenes/{scene['id']}/credentials/{active_id}")
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "CREDENTIAL_ALREADY_REVOKED"


def test_scene_listing_counts_questions() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client)
        scene = helpers.create_scene(client, name="有题场景")
        credential = helpers.issue_credential(client, scene["id"])
        payload = helpers.make_batch("cmd-count", [helpers.make_case("case-count")])
        response = helpers.upload_batch(client, credential["token"], payload)
        assert response.status_code == 201, response.text

        listing = client.get("/api/scenes").json()
        entry = next(item for item in listing["items"] if item["id"] == scene["id"])
        assert entry["question_count"] == 1
        assert entry["active_credential_count"] == 1


def test_blank_scene_name_is_rejected() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client)
        for blank in ["", "   ", "\t\n"]:
            response = client.post("/api/scenes", json={"name": blank})
            assert response.status_code == 422, response.text


def test_credential_label_length_is_enforced() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.register_admin(client)
        scene = helpers.create_scene(client)
        response = client.post(
            f"/api/scenes/{scene['id']}/credentials",
            json={"label": "x" * 201},
        )
        assert response.status_code == 422, response.text
