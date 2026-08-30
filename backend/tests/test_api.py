from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from app.features.auth import repository as auth_repository
from app.features.case_builder import repository as case_repository
from app.features.workspaces import repository as workspace_repository
from app.main import app


@pytest.fixture(autouse=True)
def reset_repositories():
    auth_repository.reset()
    workspace_repository.reset()
    case_repository.reset()


@pytest.fixture
def client():
    return TestClient(app)


def register(client: TestClient, username: str = "teacher-a") -> dict:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "password123"},
    )
    assert response.status_code == 201
    return response.json()["user"]


def create_workspace(client: TestClient) -> str:
    response = client.post("/api/workspaces", json={"name": "Stub 场景"})
    assert response.status_code == 201
    return response.json()["workspace"]["id"]


def upload_case(client: TestClient, workspace_id: str, text: str) -> dict:
    response = client.post(
        f"/api/workspaces/{workspace_id}/cases",
        data={"title": "测试案例"},
        files={"file": ("case.md", BytesIO(text.encode()), "text/markdown")},
    )
    assert response.status_code == 201
    return response.json()["case"]


def test_openapi_and_health(client: TestClient):
    health = client.get("/healthz").json()
    assert health["persistence"] == "business database"
    assert health["ai"] == "production"
    schema = client.get("/api/openapi.json").json()
    assert "/api/workspaces/{workspace_id}/cases/{case_id}/confirmation" in schema["paths"]
    assert "CaseDetail" in schema["components"]["schemas"]


def test_default_flow_waits_for_input_then_confirms(client: TestClient):
    register(client)
    workspace_id = create_workspace(client)
    case = upload_case(client, workspace_id, "客户需要一份事实准确的新闻稿。")

    response = client.post(
        f"/api/workspaces/{workspace_id}/cases/{case['id']}/draft-generation"
    )
    assert response.status_code == 200
    pending = response.json()["case"]
    assert pending["state"] == "waiting_for_input"
    question_id = pending["builder"]["pending_question"]["id"]

    response = client.post(
        f"/api/workspaces/{workspace_id}/cases/{case['id']}/answers",
        json={"question_id": question_id, "answer": "老师认可最终事实准确的新闻稿。"},
    )
    assert response.status_code == 200
    draft = response.json()["case"]
    assert draft["state"] == "waiting_for_confirmation"
    content = draft["builder"]["draft"]

    response = client.post(
        f"/api/workspaces/{workspace_id}/cases/{case['id']}/confirmation",
        json={"draft_revision": draft["builder"]["draft_revision"], "content": content},
    )
    assert response.status_code == 200
    confirmed = response.json()["case"]
    assert confirmed["state"] == "confirmed"
    assert confirmed["candidate_case"]["id"]
    assert confirmed["candidate_case"]["confirmed_by_username"] == "teacher-a"

    retry = client.post(
        f"/api/workspaces/{workspace_id}/cases/{case['id']}/confirmation",
        json={"draft_revision": confirmed["builder"]["draft_revision"], "content": content},
    )
    assert retry.status_code == 200
    assert retry.json()["case"]["candidate_case"]["id"] == confirmed["candidate_case"]["id"]


def test_parse_failed_and_ai_failed_states(client: TestClient):
    register(client)
    workspace_id = create_workspace(client)
    empty = upload_case(client, workspace_id, "   ")
    assert empty["state"] == "parse_failed"
    assert empty["builder"]["last_error"]["retryable"] is False

    failed = upload_case(client, workspace_id, "[stub:ai_failed]\n可解析案例")
    response = client.post(
        f"/api/workspaces/{workspace_id}/cases/{failed['id']}/draft-generation"
    )
    assert response.json()["case"]["state"] == "ai_failed"
    assert response.json()["case"]["builder"]["last_error"]["retryable"] is True

    response = client.post(
        f"/api/workspaces/{workspace_id}/cases/{failed['id']}/draft-generation"
    )
    assert response.json()["case"]["state"] == "waiting_for_confirmation"


def test_forbidden_workspace_and_case(client: TestClient):
    register(client, "teacher-a")
    workspace_id = create_workspace(client)
    case = upload_case(client, workspace_id, "私有案例内容")

    other = TestClient(app)
    register(other, "teacher-b")
    response = other.get(f"/api/workspaces/{workspace_id}")
    assert response.status_code == 403
    response = other.get(f"/api/workspaces/{workspace_id}/cases/{case['id']}")
    assert response.status_code == 403
