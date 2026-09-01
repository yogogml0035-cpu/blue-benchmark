"""HTTP boundary for rubric review and immutable question publication."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, status

from app.features.auth import service as auth_service
from app.features.auth.repository import UserRecord
from app.features.evaluation_sets import rubric_service as service
from app.features.evaluation_sets.rubric_schemas import (
    RubricConfirmationRequest,
    RubricDeriveRequest,
    RubricDraftResponse,
    RubricGenerateRequest,
    RubricPatchRequest,
    RubricPublishRequest,
    RubricRevisionListResponse,
)
from app.lib.schemas import ErrorResponse


router = APIRouter(prefix="/workspaces/{workspace_id}/authoring", tags=["rubric-authoring"])
common_errors = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}


@router.post(
    "/question-drafts/{question_draft_id}/rubric",
    response_model=RubricDraftResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=common_errors,
)
def start_rubric(
    payload: RubricGenerateRequest,
    workspace_id: str = Path(min_length=1),
    question_draft_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> RubricDraftResponse:
    return service.start_rubric(workspace_id, question_draft_id, payload, user)


@router.post(
    "/question-drafts/{question_draft_id}/rubric/start",
    response_model=RubricDraftResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=common_errors,
)
def confirm_and_start_rubric(
    payload: RubricGenerateRequest,
    workspace_id: str = Path(min_length=1),
    question_draft_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> RubricDraftResponse:
    return service.confirm_and_start_rubric(workspace_id, question_draft_id, payload, user)


@router.post(
    "/question-drafts/{question_draft_id}/rubric/publish",
    response_model=RubricDraftResponse,
    responses=common_errors,
)
def confirm_and_publish_automatic(
    payload: RubricPublishRequest,
    workspace_id: str = Path(min_length=1),
    question_draft_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> RubricDraftResponse:
    return service.confirm_and_publish_automatic(workspace_id, question_draft_id, payload, user)


@router.get(
    "/rubrics/{rubric_id}",
    response_model=RubricDraftResponse,
    responses=common_errors,
)
def get_rubric(
    workspace_id: str = Path(min_length=1),
    rubric_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> RubricDraftResponse:
    return service.get_rubric(workspace_id, rubric_id, user)


@router.get(
    "/question-drafts/{question_draft_id}/rubric",
    response_model=RubricDraftResponse,
    responses=common_errors,
)
def get_rubric_for_question(
    workspace_id: str = Path(min_length=1),
    question_draft_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> RubricDraftResponse:
    return service.get_rubric_for_question(workspace_id, question_draft_id, user)


@router.patch(
    "/rubrics/{rubric_id}",
    response_model=RubricDraftResponse,
    responses=common_errors,
)
def patch_rubric(
    payload: RubricPatchRequest,
    workspace_id: str = Path(min_length=1),
    rubric_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> RubricDraftResponse:
    return service.patch_rubric(workspace_id, rubric_id, payload, user)


@router.post(
    "/rubrics/{rubric_id}/confirmation",
    response_model=RubricDraftResponse,
    responses=common_errors,
)
def confirm_rubric(
    payload: RubricConfirmationRequest,
    workspace_id: str = Path(min_length=1),
    rubric_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> RubricDraftResponse:
    return service.confirm_rubric(workspace_id, rubric_id, payload, user)


@router.post(
    "/rubrics/{rubric_id}/publish",
    response_model=RubricDraftResponse,
    responses=common_errors,
)
def publish_rubric(
    payload: RubricPublishRequest,
    workspace_id: str = Path(min_length=1),
    rubric_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> RubricDraftResponse:
    return service.publish_rubric(workspace_id, rubric_id, payload, user)


@router.get(
    "/question-drafts/{question_draft_id}/revisions",
    response_model=RubricRevisionListResponse,
    responses=common_errors,
)
def list_revisions(
    workspace_id: str = Path(min_length=1),
    question_draft_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> RubricRevisionListResponse:
    return service.list_revisions(workspace_id, question_draft_id, user)


@router.post(
    "/question-drafts/{question_draft_id}/revisions/{revision_id}/derive-draft",
    response_model=RubricDraftResponse,
    responses=common_errors,
)
def derive_draft(
    payload: RubricDeriveRequest,
    workspace_id: str = Path(min_length=1),
    question_draft_id: str = Path(min_length=1),
    revision_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> RubricDraftResponse:
    return service.derive_draft(workspace_id, question_draft_id, revision_id, payload, user)
