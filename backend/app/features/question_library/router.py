"""Administrator routes for the scene-scoped question library."""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.features.auth import service as auth_service
from app.features.question_library import service
from app.features.question_library.schemas import (
    CriteriaPatchRequest,
    DeleteAcceptedResponse,
    OperationAcceptedResponse,
    QuestionCommandRequest,
    QuestionDeleteRequest,
    QuestionDetailResponse,
    QuestionLibraryResponse,
    QuestionSaveRegenerateRequest,
    QuestionStatus,
    QuestionTitleRequest,
    RunEventsResponse,
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


@router.post(
    "/{question_id}/review-reopen",
    response_model=QuestionDetailResponse,
    responses={
        401: {"description": "未登录"},
        404: {"description": "题目不存在"},
        409: {"description": "状态或版本不允许重新打开"},
    },
)
def review_reopen(
    question_id: str,
    payload: QuestionCommandRequest,
    _user=Depends(auth_service.require_current_user),
) -> QuestionDetailResponse:
    return service.review_reopen(question_id, payload)


@router.delete(
    "/{question_id}",
    status_code=202,
    response_model=DeleteAcceptedResponse,
    responses={
        401: {"description": "未登录"},
        404: {"description": "题目不存在"},
        409: {"description": "状态或版本不允许删除"},
        422: {"description": "标题确认不匹配"},
    },
)
def delete_question(
    question_id: str,
    payload: QuestionDeleteRequest,
    _user=Depends(auth_service.require_current_user),
) -> DeleteAcceptedResponse:
    """Accept a protected deletion: freeze + durable cross-store cleanup.

    202 means ACCEPTED, not deleted. Completion is only observable through
    the cleanup operation state (detail projection / event stream); the old
    "204 = row deleted = success" early-exit semantics are removed.
    """
    return service.delete_question(question_id, payload)


# ---------------------------------------------------------------------------
# Public run events: persisted log + same-origin SSE
# ---------------------------------------------------------------------------

_SSE_POLL_SECONDS = 0.5
_SSE_KEEPALIVE_SECONDS = 15.0


@router.get(
    "/{question_id}/runs/{operation_id}/events",
    response_model=RunEventsResponse,
    responses={
        401: {"description": "未登录"},
        404: {"description": "题目不存在"},
        409: {"description": "运行已被取代或删除冻结"},
    },
)
def get_run_events(
    question_id: str,
    operation_id: str,
    after_sequence: int = Query(default=0, ge=0),
    _user=Depends(auth_service.require_current_user),
) -> RunEventsResponse:
    """One page of the complete public event log (snapshot + cursor restore)."""
    return service.get_run_events(
        question_id, operation_id, after_sequence=after_sequence
    )


@router.get(
    "/{question_id}/runs/{operation_id}/events/stream",
    responses={401: {"description": "未登录"}, 404: {"description": "题目不存在"}},
)
def stream_run_events(
    question_id: str,
    operation_id: str,
    after_sequence: int = Query(default=0, ge=0),
    _user=Depends(auth_service.require_current_user),
) -> StreamingResponse:
    """Same-origin SSE over the persisted event log.

    The stream READS the database (events are persisted before they are sent),
    so it never owns, starts or restarts the job: disconnects, refreshes and
    late subscribers only move the read cursor. Terminal conditions: question
    leaves ``generating`` (done), deletion freeze (frozen), superseded
    operation (superseded), or missing question (gone).
    """

    def _event(payload: dict) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def _generate():
        last = after_sequence
        last_keepalive = time.monotonic()
        while True:
            try:
                page = service.get_run_events(
                    question_id, operation_id, after_sequence=last
                )
            except Exception as exc:  # AppError or storage failure: end the stream honestly
                code = getattr(exc, "code", "STREAM_ENDED")
                status = getattr(exc, "status_code", None)
                if code == "QUESTION_DELETING":
                    yield _event({"type": "frozen", "reason": code})
                elif status == 404:
                    yield _event({"type": "gone", "reason": code})
                else:
                    yield _event({"type": "ended", "reason": code})
                return
            for event in page.events:
                yield _event({"type": "event", **event.model_dump()})
                last = event.sequence
            if page.status != QuestionStatus.generating:
                yield _event({"type": "done", "status": page.status.value})
                return
            now = time.monotonic()
            if now - last_keepalive >= _SSE_KEEPALIVE_SECONDS:
                last_keepalive = now
                yield ": keepalive\n\n"
            time.sleep(_SSE_POLL_SECONDS)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
