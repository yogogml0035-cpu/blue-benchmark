"""Administrator routes for the scene-scoped question library."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.features.auth import service as auth_service
from app.features.question_library import service
from app.features.question_library.schemas import (
    CriteriaPatchRequest,
    OperationAcceptedResponse,
    QuestionCommandRequest,
    QuestionDetailResponse,
    QuestionLibraryResponse,
    QuestionSaveRegenerateRequest,
    QuestionStatus,
    QuestionTitleRequest,
)

router = APIRouter(prefix="/questions", tags=["question-library"])


@router.get(
    "",
    response_model=QuestionLibraryResponse,
    responses={401: {"description": "未登录"}, 404: {"description": "场景不存在"}},
)
def list_library(
    scene_id: str = Query(...),
    status: QuestionStatus | None = Query(default=None),
    _user=Depends(auth_service.require_current_user),
) -> QuestionLibraryResponse:
    return service.list_library(scene_id=scene_id, status=status)


@router.get(
    "/{question_id}",
    response_model=QuestionDetailResponse,
    responses={401: {"description": "未登录"}, 404: {"description": "题目不存在"}},
)
def get_question(
    question_id: str, _user=Depends(auth_service.require_current_user)
) -> QuestionDetailResponse:
    return service.get_detail(question_id)


@router.patch(
    "/{question_id}/title",
    response_model=QuestionDetailResponse,
    responses={
        401: {"description": "未登录"},
        404: {"description": "题目不存在"},
        409: {"description": "内容版本陈旧"},
    },
)
def update_title(
    question_id: str,
    payload: QuestionTitleRequest,
    _user=Depends(auth_service.require_current_user),
) -> QuestionDetailResponse:
    return service.update_title(question_id, payload)


@router.post(
    "/{question_id}/save-regenerate",
    response_model=OperationAcceptedResponse,
    responses={
        401: {"description": "未登录"},
        404: {"description": "题目不存在"},
        409: {"description": "内容版本陈旧"},
        422: {"description": "材料内容无效"},
    },
)
def save_and_regenerate(
    question_id: str,
    payload: QuestionSaveRegenerateRequest,
    _user=Depends(auth_service.require_current_user),
) -> OperationAcceptedResponse:
    return service.save_and_regenerate(question_id, payload)


@router.patch(
    "/{question_id}/criteria",
    response_model=QuestionDetailResponse,
    responses={
        401: {"description": "未登录"},
        404: {"description": "题目不存在"},
        409: {"description": "内容版本陈旧或生成中"},
        422: {"description": "评分维度无效"},
    },
)
def patch_criteria(
    question_id: str,
    payload: CriteriaPatchRequest,
    _user=Depends(auth_service.require_current_user),
) -> QuestionDetailResponse:
    return service.patch_criteria(question_id, payload)


@router.post(
    "/{question_id}/generation-retry",
    response_model=OperationAcceptedResponse,
    responses={
        401: {"description": "未登录"},
        404: {"description": "题目不存在"},
        409: {"description": "状态或版本不允许重试"},
    },
)
def retry_generation(
    question_id: str,
    payload: QuestionCommandRequest,
    _user=Depends(auth_service.require_current_user),
) -> OperationAcceptedResponse:
    return service.retry_generation(question_id, payload)


@router.post(
    "/{question_id}/publication",
    response_model=QuestionDetailResponse,
    responses={
        401: {"description": "未登录"},
        404: {"description": "题目不存在"},
        409: {"description": "状态不允许发布"},
    },
)
def publish(
    question_id: str,
    payload: QuestionCommandRequest,
    _user=Depends(auth_service.require_current_user),
) -> QuestionDetailResponse:
    return service.publish(question_id, payload)


@router.delete(
    "/{question_id}",
    status_code=204,
    responses={401: {"description": "未登录"}, 404: {"description": "题目不存在"}},
)
def delete_question(
    question_id: str, _user=Depends(auth_service.require_current_user)
) -> None:
    service.delete_question(question_id)
