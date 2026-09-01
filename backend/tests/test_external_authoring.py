from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from uuid import uuid4

from fastapi.testclient import TestClient

from app.lib.database import clear_business_data, session_scope
from app.lib.database.models import AuthoringConnectionRow, AuthoringExternalCommandRow, OperationJobRow
from app.lib.settings import settings
from app.features.external_authoring import service as external_service
from app.features.external_authoring.schemas import ExternalEvaluationCaseDraftRequest
from app.main import app


def _setup(client: TestClient, username: str = "external-teacher") -> tuple[str, str, str, str]:
    registered = client.post(
        "/api/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "password123"},
    )
    assert registered.status_code == 201
    workspace = client.post("/api/workspaces", json={"name": "External Workspace"})
    assert workspace.status_code == 201
    workspace_id = workspace.json()["workspace"]["id"]
    created = client.post(
        f"/api/workspaces/{workspace_id}/authoring-connections",
        json={"client_name": "真实本地 Agent"},
    )
    assert created.status_code == 201
    connection_id = created.json()["connection"]["id"]
    exchanged = client.post(
        "/api/external/authoring-connections/exchange",
        json={"connection_code": created.json()["connection_code"]},
    )
    assert exchanged.status_code == 200
    return workspace_id, connection_id, exchanged.json()["access_token"], created.json()["connection_code"]


def _payload(command_id: str = "external-command-1", content: str = "完整输入\n") -> dict:
    content_bytes = content.encode("utf-8")
    return {
        "schema_version": "1.0",
        "command_id": command_id,
        "title": "老师确认的外部题目",
        "task_requirement": "  老师原始任务\n保留前后空白  ",
        "input_files": [
            {
                "client_file_id": "input-1",
                "display_name": "input.md",
                "media_type": "text/markdown",
                "content_mode": "full",
                "content_text": content,
                "source_size_bytes": len(content_bytes),
                "source_sha256": hashlib.sha256(content_bytes).hexdigest(),
            }
        ],
        "bad_samples": [],
        "reference_answer_text": "  老师最终认可的标准答案\n",
    }


def _push(client: TestClient, token: str, payload: dict):
    return client.post(
        "/api/external/evaluation-case-drafts",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )


def test_external_draft_preserves_text_and_does_not_enqueue_ai() -> None:
    clear_business_data()
    with TestClient(app) as client:
        workspace_id, connection_id, token, code = _setup(client)
        assert client.post(
            "/api/external/authoring-connections/exchange",
            json={"connection_code": code},
        ).json()["error"]["code"] == "CONNECTION_CODE_REUSED"

        payload = _payload()
        response = _push(client, token, payload)
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["status"] == "draft_ready"
        assert f"?draft={result['draft_id']}" in result["draft_url"]

        conversation = client.get(
            f"/api/workspaces/{workspace_id}/authoring-conversations/{result['conversation_id']}"
        )
        assert conversation.status_code == 200
        view = conversation.json()["conversation"]
        draft = view["question_drafts"][0]
        assert view["status"] == "review_ready"
        assert draft["status"] == "input_answer_review"
        assert draft["input"]["task_instruction"] == payload["task_requirement"]
        assert draft["reference_answer_text"] == payload["reference_answer_text"]
        assert draft["input_files"][0]["content_text"] == payload["input_files"][0]["content_text"]
        assert draft["input_files"][0]["content_mode"] == "full"

        with session_scope() as session:
            assert session.query(OperationJobRow).count() == 0
            connection = session.get(AuthoringConnectionRow, connection_id)
            assert connection is not None
            assert connection.code_hash != code
            assert connection.token_hash != token
            receipt = session.query(AuthoringExternalCommandRow).one()
            assert receipt.payload_hash
            assert receipt.status == "ready"
            assert payload["task_requirement"] not in str(receipt.__dict__)


def test_external_command_is_idempotent_but_payload_change_conflicts() -> None:
    clear_business_data()
    with TestClient(app) as client:
        workspace_id, _, token, _ = _setup(client)
        payload = _payload()
        first = _push(client, token, payload)
        assert first.status_code == 201
        replay = _push(client, token, payload)
        assert replay.status_code == 201
        assert replay.json() == first.json()
        changed = dict(payload)
        changed["reference_answer_text"] = "另一份标准答案"
        conflict = _push(client, token, changed)
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "COMMAND_ID_REUSED"

        token_as_cookie = TestClient(app)
        token_as_cookie.cookies.set("skill_eval_session", token)
        assert token_as_cookie.get(
            f"/api/workspaces/{workspace_id}/authoring-conversations/{first.json()['conversation_id']}"
        ).status_code == 401


def test_rebind_revokes_old_token_and_tenant_cannot_borrow_workspace() -> None:
    clear_business_data()
    with TestClient(app) as client:
        workspace_id, connection_id, old_token, _ = _setup(client)
        rebound = client.post(
            f"/api/workspaces/{workspace_id}/authoring-connections",
            json={"client_name": "新本地 Agent"},
        )
        assert rebound.status_code == 201
        old_push = _push(client, old_token, _payload("old-token-command"))
        assert old_push.status_code == 401
        new_token = client.post(
            "/api/external/authoring-connections/exchange",
            json={"connection_code": rebound.json()["connection_code"]},
        ).json()["access_token"]
        assert _push(client, new_token, _payload("new-token-command")).status_code == 201

        other = TestClient(app)
        other_register = other.post(
            "/api/auth/register",
            json={"username": "other-teacher", "email": "other@example.com", "password": "password123"},
        )
        assert other_register.status_code == 201
        forged = other.delete(
            f"/api/workspaces/{workspace_id}/authoring-connections/{connection_id}",
        )
        assert forged.status_code == 403


def test_external_payload_rejects_truncation_private_bad_sample_and_non_text() -> None:
    clear_business_data()
    with TestClient(app) as client:
        _, _, token, _ = _setup(client)
        truncated = _payload("truncated")
        truncated["input_files"][0]["content_text"] = "截断"
        response = _push(client, token, truncated)
        assert response.status_code == 422

        private = _payload("private")
        private["bad_samples"] = [
            {
                "id": "bad-1",
                "source_ref": "real-execution-1",
                "content_text": "结果正文",
                "teacher_feedback_texts": ["这个不行"],
                "reason_summary": "系统提示要求这样做",
            }
        ]
        response = _push(client, token, private)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "BAD_SAMPLE_PRIVATE_CONTENT"

        vague = _payload("vague")
        vague["bad_samples"] = [
            {
                "id": "bad-1",
                "source_ref": "real-execution-1",
                "content_text": "结果正文",
                "teacher_feedback_texts": ["这个不行"],
                "reason_summary": "内容不符合老师要求",
            }
        ]
        response = _push(client, token, vague)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "BAD_SAMPLE_FEEDBACK_TOO_VAGUE"

        non_text = _payload("non-text")
        non_text["input_files"][0]["display_name"] = "input.pdf"
        non_text["input_files"][0]["media_type"] = "application/pdf"
        response = _push(client, token, non_text)
        assert response.status_code == 422


def test_external_input_file_can_be_edited_by_web_session_only() -> None:
    clear_business_data()
    with TestClient(app) as client:
        workspace_id, _, token, _ = _setup(client)
        created = _push(client, token, _payload("editable", "原内容\n"))
        assert created.status_code == 201
        conversation_id = created.json()["conversation_id"]
        draft_id = created.json()["draft_id"]
        view = client.get(f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation_id}").json()["conversation"]
        draft = view["question_drafts"][0]
        update = client.patch(
            f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation_id}/question-drafts/{draft_id}/input-answer",
            json={
                "command_id": "web-edit-1",
                "draft_revision": draft["revision"],
                "input": draft["input"],
                "reference_answer_text": draft["reference_answer_text"],
                "bad_samples": [],
                "input_file_updates":[{"file_id": draft["input_files"][0]["file_id"], "content_text": "网站修改后\n"}],
            },
        )
        assert update.status_code == 200, update.text
        assert update.json()["conversation"]["question_drafts"][0]["input_files"][0]["content_text"] == "网站修改后\n"


def test_empty_workspace_studio_is_a_recoverable_snapshot() -> None:
    clear_business_data()
    with TestClient(app) as client:
        registered = client.post(
            "/api/auth/register",
            json={"username": "empty-studio", "email": "empty-studio@example.com", "password": "password123"},
        )
        assert registered.status_code == 201
        workspace = client.post("/api/workspaces", json={"name": "Empty Studio"})
        assert workspace.status_code == 201
        workspace_id = workspace.json()["workspace"]["id"]
        studio = client.get(f"/api/workspaces/{workspace_id}/upload-batches/studio")
        assert studio.status_code == 200
        assert studio.json()["batch_id"] is None
        assert studio.json()["batch_status"] == "none"
        assert studio.json()["next_action"] == {"kind": "none", "label": "上传资料"}


def test_crashed_external_request_leases_are_recoverable() -> None:
    clear_business_data()
    with TestClient(app) as client:
        _, connection_id, token, _ = _setup(client, "lease-teacher")
        payload = _payload("stale-command")
        typed = ExternalEvaluationCaseDraftRequest.model_validate(payload)
        digest = external_service._payload_hash(typed)
        stale_at = datetime.now(timezone.utc) - timedelta(seconds=settings.external_authoring_request_lease_seconds + 1)
        with session_scope() as session:
            connection = session.get(AuthoringConnectionRow, connection_id)
            assert connection is not None
            connection.active_request_count = settings.external_authoring_max_concurrent_requests
            connection.last_request_at = stale_at
            session.add(
                AuthoringExternalCommandRow(
                    id=str(uuid4()),
                    connection_id=connection_id,
                    command_id=typed.command_id,
                    payload_hash=digest,
                    status="creating",
                    conversation_id=None,
                    draft_id=None,
                    created_at=stale_at,
                    completed_at=None,
                )
            )
        response = _push(client, token, payload)
        assert response.status_code == 201, response.text
