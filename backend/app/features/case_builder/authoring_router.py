"""HTTP boundary for the first-stage authoring conversation."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Path, Request, status
from fastapi.responses import StreamingResponse

from app.features.auth import service as auth_service
from app.features.auth.repository import UserRecord
from app.features.case_builder import authoring_service as service
from app.features.case_builder.authoring_schemas import (
    AuthoringConversationCreateRequest,
    AuthoringConversationResponse,
    AuthoringContinuityResetRequest,
    AuthoringEventListResponse,
    AuthoringMessageRequest,
    AuthoringRetryRequest,
    InputAnswerConfirmationRequest,
    InputAnswerPatchRequest,
    QuestionBoundaryRequest,
)
from app.lib.schemas import ErrorResponse


router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["authoring"])
common_errors = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


@router.post(
    "/authoring-conversations",
    response_model=AuthoringConversationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=common_errors,
)
def create_conversation(
    payload: AuthoringConversationCreateRequest,
    workspace_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> AuthoringConversationResponse:
    return service.create_conversation(workspace_id, payload, user)


@router.get(
    "/authoring-conversations/{conversation_id}",
    response_model=AuthoringConversationResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_conversation(
    workspace_id: str = Path(min_length=1),
    conversation_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> AuthoringConversationResponse:
    return service.get_conversation(workspace_id, conversation_id, user)


@router.post(
    "/authoring-conversations/{conversation_id}/messages",
    response_model=AuthoringConversationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=common_errors,
)
def post_message(
    payload: AuthoringMessageRequest,
    workspace_id: str = Path(min_length=1),
    conversation_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> AuthoringConversationResponse:
    return service.post_message(workspace_id, conversation_id, payload, user)


@router.get(
    "/authoring-conversations/{conversation_id}/events",
    response_class=StreamingResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def stream_events(
    request: Request,
    workspace_id: str = Path(min_length=1),
    conversation_id: str = Path(min_length=1),
    after: int = 0,
    user: UserRecord = Depends(auth_service.require_current_user),
) -> StreamingResponse:
    # Last-Event-ID is a public per-conversation sequence, never a database
    # event id or an Agent checkpoint id.
    header_cursor = request.headers.get("last-event-id")
    if header_cursor and header_cursor.isdigit():
        after = max(after, int(header_cursor))
    snapshot: AuthoringEventListResponse = service.list_events(
        workspace_id,
        conversation_id,
        user,
        after=after,
    )

    def body():
        if not snapshot.events:
            # A finite heartbeat lets the browser reconnect without tying the
            # Worker lifecycle to an SSE connection.
            yield ": heartbeat\n\n"
            return
        for event in snapshot.events:
            yield f"id: {event.sequence}\n"
            yield f"event: {event.kind.value}\n"
            yield f"data: {json.dumps(event.payload, ensure_ascii=False, separators=(',', ':'))}\n\n"

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/authoring-conversations/{conversation_id}/question-boundaries",
    response_model=AuthoringConversationResponse,
    responses=common_errors,
)
def mutate_boundaries(
    payload: QuestionBoundaryRequest,
    workspace_id: str = Path(min_length=1),
    conversation_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> AuthoringConversationResponse:
    return service.mutate_boundaries(workspace_id, conversation_id, payload, user)


@router.patch(
    "/authoring-conversations/{conversation_id}/question-drafts/{draft_id}/input-answer",
    response_model=AuthoringConversationResponse,
    responses=common_errors,
)
def patch_input_answer(
    payload: InputAnswerPatchRequest,
    workspace_id: str = Path(min_length=1),
    conversation_id: str = Path(min_length=1),
    draft_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> AuthoringConversationResponse:
    return service.patch_input_answer(workspace_id, conversation_id, draft_id, payload, user)


@router.post(
    "/authoring-conversations/{conversation_id}/question-drafts/{draft_id}/input-answer-confirmation",
    response_model=AuthoringConversationResponse,
    responses=common_errors,
)
def confirm_input_answer(
    payload: InputAnswerConfirmationRequest,
    workspace_id: str = Path(min_length=1),
    conversation_id: str = Path(min_length=1),
    draft_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> AuthoringConversationResponse:
    return service.confirm_input_answer(workspace_id, conversation_id, draft_id, payload, user)


@router.post(
    "/authoring-conversations/{conversation_id}/retry",
    response_model=AuthoringConversationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=common_errors,
)
def retry_conversation(
    payload: AuthoringRetryRequest,
    workspace_id: str = Path(min_length=1),
    conversation_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> AuthoringConversationResponse:
    return service.retry_conversation(workspace_id, conversation_id, payload, user)


@router.post(
    "/authoring-conversations/{conversation_id}/continuity-reset",
    response_model=AuthoringConversationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=common_errors,
)
def reset_continuity(
    payload: AuthoringContinuityResetRequest,
    workspace_id: str = Path(min_length=1),
    conversation_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> AuthoringConversationResponse:
    return service.reset_continuity(workspace_id, conversation_id, payload, user)
