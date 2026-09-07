"""Scene administration: folders, credentials, single-admin guard."""

from fastapi.testclient import TestClient

from app.lib.database import clear_business_data
from app.main import app
from tests import helpers


def test_single_admin_guard_blocks_second_registration() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.login_admin(client)
    # The register entry is gone; a second admin cannot be created over HTTP.
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/register",
            json={"username": "second-admin", "password": "another-password-1"},
        )
        assert response.status_code == 404
    # Startup seeding stays idempotent: still exactly one admin, and a login
    # with the old self-chosen credentials fails.
    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"identifier": "second-admin", "password": "another-password-1"},
        )
        assert login.status_code == 401


def test_scene_requires_admin_session() -> None:
    clear_business_data()
    with TestClient(app) as client:
        response = client.post("/api/scenes", json={"name": "场景A"})
        assert response.status_code == 401
        response = client.get("/api/scenes")
        assert response.status_code == 401


def test_scene_lifecycle_and_credential_one_to_one_rules() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.login_admin(client)
        scene = helpers.create_scene(client, name="媒体场景")

        # Duplicate names conflict.
        duplicate = client.post("/api/scenes", json={"name": "媒体场景"})
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "SCENE_NAME_EXISTS"

        created = helpers.create_credential(client, scene["id"], label="首次凭证")
        assert created["token"].startswith("sep_")
        plaintext = created["token"]

        # Status views return the single credential masked, never the plaintext.
        status = client.get(f"/api/scenes/{scene['id']}")
        assert status.status_code == 200
        body = status.json()
        assert plaintext not in status.text
        assert body["scene"]["active_credential_count"] == 1
        assert body["credential"]["status"] == "active"
        assert body["credential"]["label"] == "首次凭证"
        assert body["credential"]["token_preview"].startswith("sep_")
        assert "…" in body["credential"]["token_preview"]
        assert "token" not in body["credential"]

        # The reveal endpoint returns exactly the issued plaintext, no-store.
        revealed = client.get(f"/api/scenes/{scene['id']}/credential")
        assert revealed.status_code == 200
        assert revealed.json() == {"credential_id": created["credential_id"], "token": plaintext}
        assert revealed.headers.get("cache-control") == "no-store"

        # Replacing revokes the current credential and issues a new one.
        replaced = client.post(
            f"/api/scenes/{scene['id']}/credentials", json={"label": "替换"}
        )
        assert replaced.status_code == 201
        new_token = replaced.json()["token"]
        assert new_token != plaintext

        status = client.get(f"/api/scenes/{scene['id']}").json()
        # Only the current credential is exposed; no revoked history.
        assert status["credential"]["credential_id"] == replaced.json()["credential_id"]
        assert status["credential"]["label"] == "替换"
        assert status["scene"]["active_credential_count"] == 1
        assert plaintext not in str(status)

        # The replaced token stops working immediately.
        stale = client.get(
            "/api/external/connection", headers={"Authorization": f"Bearer {plaintext}"}
        )
        assert stale.status_code == 401

        # Reveal now returns the replacement's plaintext.
        assert client.get(f"/api/scenes/{scene['id']}/credential").json()["token"] == new_token

        # Manual revoke is idempotency-safe: second revoke conflicts.
        active_id = status["credential"]["credential_id"]
        revoke = client.delete(f"/api/scenes/{scene['id']}/credentials/{active_id}")
        assert revoke.status_code == 200
        again = client.delete(f"/api/scenes/{scene['id']}/credentials/{active_id}")
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "CREDENTIAL_ALREADY_REVOKED"

        # After revoking the only credential there is none to reveal.
        assert client.get(f"/api/scenes/{scene['id']}").json()["credential"] is None
        missing = client.get(f"/api/scenes/{scene['id']}/credential")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "NO_ACTIVE_CREDENTIAL"


def test_scene_listing_counts_questions() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.login_admin(client)
        scene = helpers.create_scene(client, name="有题场景")
        credential = helpers.create_credential(client, scene["id"])
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
        helpers.login_admin(client)
        for blank in ["", "   ", "\t\n"]:
            response = client.post("/api/scenes", json={"name": blank})
            assert response.status_code == 422, response.text


def test_credential_label_length_is_enforced() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.login_admin(client)
        scene = helpers.create_scene(client)
        response = client.post(
            f"/api/scenes/{scene['id']}/credentials",
            json={"label": "x" * 201},
        )
        assert response.status_code == 422, response.text


def test_external_connection_status_reports_scene_without_token() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.login_admin(client)
        scene = helpers.create_scene(client, name="连接场景")
        credential = helpers.create_credential(client, scene["id"], label="ci")
        headers = {"Authorization": f"Bearer {credential['token']}"}

        response = client.get("/api/external/connection", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "connected"
        assert body["scene_id"] == scene["id"]
        assert body["scene_name"] == "连接场景"
        assert body["label"] == "ci"
        # The token (and its hash) must never be echoed.
        assert credential["token"] not in response.text
        assert "token" not in body

        # An invalid token is rejected.
        bad = client.get(
            "/api/external/connection", headers={"Authorization": "Bearer sep_wrong"}
        )
        assert bad.status_code == 401


def test_scene_update_renames_and_rejects_duplicates() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.login_admin(client)
        scene = helpers.create_scene(client, name="原名称")
        other = helpers.create_scene(client, name="其他场景")

        updated = client.patch(
            f"/api/scenes/{scene['id']}",
            json={"name": "新名称", "description": "新的描述"},
        )
        assert updated.status_code == 200, updated.text
        body = updated.json()
        assert body["name"] == "新名称"
        assert body["description"] == "新的描述"
        # The list view reflects the rename.
        listing = client.get("/api/scenes").json()
        assert any(item["name"] == "新名称" for item in listing["items"])

        # Renaming onto another scene's name conflicts.
        conflict = client.patch(
            f"/api/scenes/{scene['id']}", json={"name": "其他场景", "description": None}
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "SCENE_NAME_EXISTS"
        assert other["id"] != scene["id"]

        # Blank and missing targets are rejected.
        blank = client.patch(f"/api/scenes/{scene['id']}", json={"name": "   ", "description": None})
        assert blank.status_code == 422
        missing = client.patch("/api/scenes/no-such-scene", json={"name": "任意", "description": None})
        assert missing.status_code == 404

        # Clearing the description stores null.
        cleared = client.patch(
            f"/api/scenes/{scene['id']}", json={"name": "新名称", "description": None}
        )
        assert cleared.status_code == 200
        assert cleared.json()["description"] is None


def test_empty_scene_delete_cascades_credentials() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.login_admin(client)
        scene = helpers.create_scene(client, name="待删除场景")
        helpers.create_credential(client, scene["id"], label="将随场景失效")

        deleted = client.delete(f"/api/scenes/{scene['id']}")
        assert deleted.status_code == 204

        # The scene and its credential status are gone.
        assert client.get(f"/api/scenes/{scene['id']}").status_code == 404
        listing = client.get("/api/scenes").json()
        assert all(item["id"] != scene["id"] for item in listing["items"])


def test_nonempty_scene_delete_is_rejected_at_api_layer() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.login_admin(client)
        scene = helpers.create_scene(client, name="有题场景")
        credential = helpers.create_credential(client, scene["id"])
        response = helpers.upload_batch(
            client, credential["token"], helpers.make_batch("cmd-del", [helpers.make_case("case-del")])
        )
        assert response.status_code == 201, response.text

        deleted = client.delete(f"/api/scenes/{scene['id']}")
        assert deleted.status_code == 409
        assert deleted.json()["error"]["code"] == "SCENE_NOT_EMPTY"

        # Data stays intact after the rejected delete.
        status = client.get(f"/api/scenes/{scene['id']}").json()
        assert status["scene"]["question_count"] == 1
        assert client.get(f"/api/questions?scene_id={scene['id']}").json()["total"] == 1


def test_credential_create_and_reveal_responses_are_not_cacheable() -> None:
    clear_business_data()
    with TestClient(app) as client:
        helpers.login_admin(client)
        scene = helpers.create_scene(client, name="缓存控制场景")

        created = client.post(f"/api/scenes/{scene['id']}/credentials", json={"label": "a"})
        assert created.status_code == 201
        assert created.headers.get("cache-control") == "no-store"
        assert created.headers.get("pragma") == "no-cache"

        revealed = client.get(f"/api/scenes/{scene['id']}/credential")
        assert revealed.status_code == 200
        assert revealed.headers.get("cache-control") == "no-store"
        assert revealed.headers.get("pragma") == "no-cache"

        # Status endpoints never carry plaintext, cacheable or not.
        status = client.get(f"/api/scenes/{scene['id']}")
        assert created.json()["token"] not in status.text
        listing = client.get("/api/scenes")
        assert created.json()["token"] not in listing.text
