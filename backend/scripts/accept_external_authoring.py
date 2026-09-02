"""Run the external authoring contract against a live local HTTP API.

This flow deliberately does not enqueue AI: external authoring is a
deterministic draft-ingestion boundary. The real Provider/Worker E2E remains a
separate gate; this script proves the client-facing HTTP and browser handoff.
Only stage markers are printed.
"""

from __future__ import annotations

import argparse
import hashlib
import secrets
from pathlib import Path

import httpx


class AcceptanceFailure(RuntimeError):
    def __init__(self, stage: str) -> None:
        super().__init__(stage)
        self.stage = stage


def require(condition: bool, stage: str) -> None:
    if not condition:
        raise AcceptanceFailure(stage)


def stage(name: str) -> None:
    print(f"EXTERNAL_AUTHORING_E2E_STAGE={name}", flush=True)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run external authoring against a live local API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--samples-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _args()
    markdown = sorted(args.samples_dir.glob("*.md"))
    require(len(markdown) == 1, "sample_markdown")
    content = markdown[0].read_text(encoding="utf-8")
    content_bytes = content.encode("utf-8")
    suffix = secrets.token_hex(5)
    username = f"external-e2e-{suffix}"
    password = "password123"

    # This script is a local API acceptance client; system proxy settings must
    # not intercept loopback traffic and turn a healthy request into a 502.
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=30.0, trust_env=False) as client:
        stage("register")
        response = client.post(
            "/api/auth/register",
            json={"username": username, "email": f"{username}@example.com", "password": password},
        )
        require(response.status_code == 201, "register")

        stage("connection")
        workspace = client.post("/api/workspaces", json={"name": "外部真实 HTTP 验收"})
        require(workspace.status_code == 201, "workspace")
        workspace_id = workspace.json()["workspace"]["id"]
        connection = client.post(
            f"/api/workspaces/{workspace_id}/authoring-connections",
            json={"client_name": "live-external-e2e"},
        )
        require(connection.status_code == 201, "connection_create")
        exchange = client.post(
            "/api/external/authoring-connections/exchange",
            json={"connection_code": connection.json()["connection_code"]},
        )
        require(exchange.status_code == 200, "connection_exchange")
        token = exchange.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        stage("push")
        payload = {
            "schema_version": "1.0",
            "command_id": f"live-{suffix}",
            "title": "EvalData 外部题稿",
            "task_requirement": "  老师在本地 Agent 中输入的原始任务\n请逐字保留。  ",
            "input_files": [
                {
                    "client_file_id": "evaldata-brief",
                    "display_name": markdown[0].name,
                    "media_type": "text/markdown",
                    "content_mode": "full",
                    "content_text": content,
                    "source_size_bytes": len(content_bytes),
                    "source_sha256": hashlib.sha256(content_bytes).hexdigest(),
                }
            ],
            "bad_samples": [],
            "reference_answer_text": "老师最终认可的完整标准答案。",
        }
        pushed = client.post("/api/external/evaluation-case-drafts", json=payload, headers=headers)
        require(pushed.status_code == 201, "push")
        result = pushed.json()
        require(result["status"] == "draft_ready" and "?draft=" in result["draft_url"], "draft_link")

        stage("idempotent_replay")
        replay = client.post("/api/external/evaluation-case-drafts", json=payload, headers=headers)
        require(replay.status_code == 201 and replay.json() == result, "idempotent_replay")

        stage("web_review")
        conversation = client.get(
            f"/api/workspaces/{workspace_id}/authoring-conversations/{result['conversation_id']}"
        )
        require(conversation.status_code == 200, "web_review")
        draft = conversation.json()["conversation"]["question_drafts"][0]
        require(draft["input"]["task_instruction"] == payload["task_requirement"], "task_requirement_exact")
        require(draft["input_files"][0]["content_text"] == content, "input_file_exact")

        stage("revoke")
        revoked = client.delete(
            f"/api/workspaces/{workspace_id}/authoring-connections/{connection.json()['connection']['id']}"
        )
        require(revoked.status_code == 200, "revoke")
        denied = client.post(
            "/api/external/evaluation-case-drafts",
            json={**payload, "command_id": f"after-revoke-{suffix}"},
            headers=headers,
        )
        require(denied.status_code == 401, "revoked_token")

    stage("complete")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AcceptanceFailure as exc:
        print(f"EXTERNAL_AUTHORING_E2E=FAIL stage={exc.stage}")
        raise SystemExit(1)
