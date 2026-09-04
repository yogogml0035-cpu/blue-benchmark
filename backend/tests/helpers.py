"""Shared setup helpers for contract tests."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient


def register_admin(client: TestClient, username: str = "admin") -> dict[str, Any]:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "platform-admin-password"},
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["user"]


def create_scene(client: TestClient, name: str | None = None) -> dict[str, Any]:
    response = client.post(
        "/api/scenes",
        json={"name": name or f"scene-{uuid.uuid4().hex[:8]}", "description": "测试场景"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_credential(client: TestClient, scene_id: str, label: str = "ci") -> dict[str, Any]:
    """Create-or-replace the scene's single credential (1:1 model)."""
    response = client.post(
        f"/api/scenes/{scene_id}/credentials", json={"label": label}
    )
    assert response.status_code == 201, response.text
    return response.json()


def upload_batch(
    client: TestClient, token: str, payload: dict[str, Any]
) -> Any:
    return client.post(
        "/api/external/question-batches",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )


def make_case(
    client_case_id: str = "case-1",
    *,
    title: str = "新闻稿改写",
    task_prompt: str = "请把提供的新闻素材改写成一段正式新闻稿。",
    reference_answer: str = "这是一份老师认可的标准答案。",
    reference_examples: list[dict[str, Any]] | None = None,
    bad_cases: list[dict[str, Any]] | None = None,
    memory_materials: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "client_case_id": client_case_id,
        "title": title,
        "task_prompt": task_prompt,
        "reference_examples": reference_examples
        if reference_examples is not None
        else [
            {
                "client_ref_id": "ref-1",
                "source_name": "新闻素材",
                "content_text": "老师提供并且 Agent 实际读取过的素材正文。",
            }
        ],
        "bad_cases": bad_cases
        if bad_cases is not None
        else [
            {
                "content_text": "一份被老师否定的初稿。",
                "teacher_feedback_texts": ["语气太随意，不符合新闻稿要求。"],
                "reason_summary": "语体不符合正式新闻稿规范。",
            }
        ],
        "reference_answer": reference_answer,
        "memory_materials": memory_materials
        if memory_materials is not None
        else [
            {
                "client_ref_id": "mem-1",
                "source_label": "业务记忆",
                "content_text": "本轮实际加载的相关记忆原文。",
            }
        ],
    }


def make_batch(command_id: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": "1.0", "command_id": command_id, "cases": cases}


def run_worker_until_idle() -> int:
    """Drive the fake worker synchronously until no jobs remain."""

    from app.lib.operations.worker import default_worker

    worker = default_worker()
    rounds = 0
    while worker.run_once():
        rounds += 1
        if rounds > 100:  # pragma: no cover - defensive
            raise RuntimeError("worker did not reach idle state")
    return rounds
