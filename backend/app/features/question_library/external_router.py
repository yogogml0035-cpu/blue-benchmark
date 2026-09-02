"""External batch intake authenticated by scene upload credentials."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.features.question_library import service
from app.features.question_library.schemas import BatchUploadRequest, BatchUploadResponse
from app.features.scenes.schemas import SceneConnectionStatusView
from app.features.scenes.service import (
    ScenePrincipal,
    connection_status,
    require_scene_principal,
)

router = APIRouter(prefix="/external", tags=["external-intake"])


@router.get(
    "/connection",
    response_model=SceneConnectionStatusView,
    responses={401: {"description": "凭证缺失或无效"}},
)
def get_connection_status(
    principal: ScenePrincipal = Depends(require_scene_principal),
) -> SceneConnectionStatusView:
    return connection_status(principal)


@router.post(
    "/question-batches",
    response_model=BatchUploadResponse,
    status_code=201,
    responses={
        401: {"description": "凭证缺失或无效"},
        409: {"description": "命令冲突或正在处理"},
        422: {"description": "批次内容校验失败"},
    },
)
def upload_question_batch(
    payload: BatchUploadRequest,
    principal: ScenePrincipal = Depends(require_scene_principal),
) -> BatchUploadResponse:
    return service.batch_upload(principal, payload)
