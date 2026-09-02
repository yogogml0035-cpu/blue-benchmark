"""Scene administration: folders, upload credentials and credential principals."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.features.scenes import repository
from app.features.scenes.schemas import (
    CREDENTIAL_LABEL_MAX_LENGTH,
    SceneCredentialIssuedView,
    SceneCredentialStatusView,
    SceneCreateRequest,
    SceneListResponse,
    SceneStatusResponse,
    SceneView,
)
from app.lib.database import session_scope
from app.lib.errors import AppError

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class ScenePrincipal:
    credential_id: str
    scene_id: str


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _scene_view(summary: repository.SceneSummary) -> SceneView:
    return SceneView(
        id=summary.scene.id,
        name=summary.scene.name,
        description=summary.scene.description,
        created_at=_iso(summary.scene.created_at) or "",
        question_count=summary.question_count,
        active_credential_count=summary.active_credential_count,
    )


def create_scene(payload: SceneCreateRequest) -> SceneView:
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        try:
            summary = repository.SceneSummary(
                scene=repository.create_scene(
                    session, name=payload.name.strip(), description=payload.description, now=now
                ),
                question_count=0,
                active_credential_count=0,
            )
        except ValueError as exc:
            if str(exc) == "SCENE_NAME_EXISTS":
                raise AppError(409, "SCENE_NAME_EXISTS", "同名场景已经存在。") from exc
            raise
        return _scene_view(summary)


def list_scenes() -> SceneListResponse:
    with session_scope() as session:
        summaries = repository.list_scene_summaries(session)
    return SceneListResponse(items=[_scene_view(item) for item in summaries])


def get_scene_or_404(scene_id: str) -> SceneStatusResponse:
    with session_scope() as session:
        scene = repository.get_scene(session, scene_id)
        if scene is None:
            raise AppError(404, "RESOURCE_NOT_FOUND", "场景不存在。")
        credentials = repository.list_credentials(session, scene_id)
        question_count = repository.count_questions_for_scene(session, scene_id)
        active_count = repository.count_active_credentials(session, scene_id)
    return SceneStatusResponse(
        scene=SceneView(
            id=scene.id,
            name=scene.name,
            description=scene.description,
            created_at=_iso(scene.created_at) or "",
            question_count=question_count,
            active_credential_count=active_count,
        ),
        credentials=[
            SceneCredentialStatusView(
                credential_id=item.id,
                label=item.label,
                status="revoked" if item.revoked_at else "active",
                created_at=_iso(item.created_at) or "",
                last_used_at=_iso(item.last_used_at),
                revoked_at=_iso(item.revoked_at),
                revoked_reason=item.revoked_reason,
            )
            for item in credentials
        ],
    )


def _validate_label(label: str | None) -> str | None:
    if label is None:
        return None
    stripped = label.strip()
    if not stripped:
        return None
    if len(stripped) > CREDENTIAL_LABEL_MAX_LENGTH:
        raise AppError(422, "VALIDATION_ERROR", "凭证标签过长。")
    return stripped


def issue_credential(scene_id: str, label: str | None) -> SceneCredentialIssuedView:
    label = _validate_label(label)
    now = datetime.now(timezone.utc)
    plaintext = f"sep_{secrets.token_urlsafe(36)}"
    hashed = repository.token_hash(plaintext)
    with session_scope() as session:
        if repository.get_scene(session, scene_id) is None:
            raise AppError(404, "RESOURCE_NOT_FOUND", "场景不存在。")
        record = repository.create_credential(
            session, scene_id=scene_id, hashed=hashed, label=label, now=now
        )
    return SceneCredentialIssuedView(
        credential_id=record.id,
        scene_id=scene_id,
        token=plaintext,
        created_at=_iso(record.created_at) or "",
    )


def rotate_credentials(scene_id: str, label: str | None) -> SceneCredentialIssuedView:
    """Revoke every active credential of the scene, then issue one replacement."""

    label = _validate_label(label)
    now = datetime.now(timezone.utc)
    plaintext = f"sep_{secrets.token_urlsafe(36)}"
    hashed = repository.token_hash(plaintext)
    with session_scope() as session:
        if repository.get_scene(session, scene_id) is None:
            raise AppError(404, "RESOURCE_NOT_FOUND", "场景不存在。")
        repository.revoke_scene_credentials(session, scene_id, reason="rotated", now=now)
        record = repository.create_credential(
            session, scene_id=scene_id, hashed=hashed, label=label, now=now
        )
    return SceneCredentialIssuedView(
        credential_id=record.id,
        scene_id=scene_id,
        token=plaintext,
        created_at=_iso(record.created_at) or "",
    )


def revoke_credential(scene_id: str, credential_id: str) -> SceneCredentialStatusView:
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        credentials = repository.list_credentials(session, scene_id)
        if not any(item.id == credential_id and item.scene_id == scene_id for item in credentials):
            raise AppError(404, "RESOURCE_NOT_FOUND", "场景凭证不存在。")
        updated = repository.revoke_credential(
            session, credential_id, reason="manual", now=now
        )
        if updated is None:
            raise AppError(409, "CREDENTIAL_ALREADY_REVOKED", "该凭证已经被撤销。")
    return SceneCredentialStatusView(
        credential_id=updated.id,
        label=updated.label,
        status="revoked",
        created_at=_iso(updated.created_at) or "",
        last_used_at=_iso(updated.last_used_at),
        revoked_at=_iso(updated.revoked_at),
        revoked_reason=updated.revoked_reason,
    )


def require_scene_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> ScenePrincipal:
    if credentials is None or not credentials.credentials.strip():
        raise AppError(401, "CREDENTIAL_REQUIRED", "缺少场景上传凭证。")
    token = credentials.credentials.strip()
    hashed = repository.token_hash(token)
    with session_scope() as session:
        record = repository.get_credential_by_hash(session, hashed)
        if record is None or record.revoked_at is not None:
            raise AppError(401, "CREDENTIAL_INVALID", "场景上传凭证无效或已被撤销。")
        repository.mark_credential_used(session, record.id, datetime.now(timezone.utc))
    return ScenePrincipal(credential_id=record.id, scene_id=record.scene_id)
