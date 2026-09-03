"""Administrator routes for scene folders and their upload credentials."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app.features.auth import service as auth_service
from app.features.scenes import service as scene_service
from app.features.scenes.schemas import (
    SceneCredentialIssueRequest,
    SceneCredentialIssuedView,
    SceneCredentialStatusView,
    SceneCreateRequest,
    SceneListResponse,
    SceneStatusResponse,
    SceneUpdateRequest,
    SceneView,
)

router = APIRouter(prefix="/scenes", tags=["scenes"])

# Issue/rotate responses carry a one-time plaintext token. They must never be
# cached by browsers, proxies, or the Next.js same-origin rewrite layer.
_NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


@router.post(
    "",
    response_model=SceneView,
    status_code=201,
    responses={401: {"description": "未登录"}, 409: {"description": "同名场景已存在"}},
)
def create_scene(
    payload: SceneCreateRequest,
    _user=Depends(auth_service.require_current_user),
) -> SceneView:
    return scene_service.create_scene(payload)


@router.get("", response_model=SceneListResponse, responses={401: {"description": "未登录"}})
def list_scenes(_user=Depends(auth_service.require_current_user)) -> SceneListResponse:
    return scene_service.list_scenes()


@router.get(
    "/{scene_id}",
    response_model=SceneStatusResponse,
    responses={401: {"description": "未登录"}, 404: {"description": "场景不存在"}},
)
def get_scene_status(
    scene_id: str, _user=Depends(auth_service.require_current_user)
) -> SceneStatusResponse:
    return scene_service.get_scene_or_404(scene_id)


@router.patch(
    "/{scene_id}",
    response_model=SceneView,
    responses={
        401: {"description": "未登录"},
        404: {"description": "场景不存在"},
        409: {"description": "同名场景已存在"},
    },
)
def update_scene(
    scene_id: str,
    payload: SceneUpdateRequest,
    _user=Depends(auth_service.require_current_user),
) -> SceneView:
    return scene_service.update_scene(scene_id, payload)


@router.delete(
    "/{scene_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        401: {"description": "未登录"},
        404: {"description": "场景不存在"},
        409: {"description": "场景仍有题目"},
    },
)
def delete_scene(
    scene_id: str, _user=Depends(auth_service.require_current_user)
) -> None:
    scene_service.delete_empty_scene(scene_id)


@router.post(
    "/{scene_id}/credentials",
    response_model=SceneCredentialIssuedView,
    status_code=201,
    responses={401: {"description": "未登录"}, 404: {"description": "场景不存在"}},
)
def issue_credential(
    scene_id: str,
    payload: SceneCredentialIssueRequest,
    response: Response,
    _user=Depends(auth_service.require_current_user),
) -> SceneCredentialIssuedView:
    response.headers.update(_NO_STORE_HEADERS)
    return scene_service.issue_credential(scene_id, payload.label)


@router.post(
    "/{scene_id}/credentials/rotation",
    response_model=SceneCredentialIssuedView,
    status_code=201,
    responses={401: {"description": "未登录"}, 404: {"description": "场景不存在"}},
)
def rotate_credentials(
    scene_id: str,
    payload: SceneCredentialIssueRequest,
    response: Response,
    _user=Depends(auth_service.require_current_user),
) -> SceneCredentialIssuedView:
    response.headers.update(_NO_STORE_HEADERS)
    return scene_service.rotate_credentials(scene_id, payload.label)


@router.delete(
    "/{scene_id}/credentials/{credential_id}",
    response_model=SceneCredentialStatusView,
    responses={
        401: {"description": "未登录"},
        404: {"description": "场景凭证不存在"},
        409: {"description": "凭证已被撤销"},
    },
)
def revoke_credential(
    scene_id: str,
    credential_id: str,
    _user=Depends(auth_service.require_current_user),
) -> SceneCredentialStatusView:
    return scene_service.revoke_credential(scene_id, credential_id)
