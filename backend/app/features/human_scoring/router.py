"""HTTP boundary for external answer submission and human scoring."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Path, UploadFile, status

from app.features.auth import service as auth_service
from app.features.auth.repository import UserRecord
from app.features.human_scoring import schemas, service
from app.lib.schemas import ErrorResponse


router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["human-scoring"])
common_errors = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}


@router.post(
    "/question-revisions/{question_revision_id}/submissions",
    response_model=schemas.HumanSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={**common_errors, 413: {"model": ErrorResponse}},
)
def create_pasted_submission(
    payload: schemas.SubmissionCreateRequest,
    workspace_id: str = Path(min_length=1),
    question_revision_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> schemas.HumanSubmissionResponse:
    return service.create_pasted_submission(workspace_id, question_revision_id, payload, user)


@router.post(
    "/question-revisions/{question_revision_id}/submissions/upload",
    response_model=schemas.HumanSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={**common_errors, 413: {"model": ErrorResponse}, 415: {"model": ErrorResponse}},
)
async def create_uploaded_submission(
    command_id: Annotated[str, Form(min_length=1, max_length=255)],
    file: Annotated[list[UploadFile], File(min_length=1, max_length=1)],
    workspace_id: str = Path(min_length=1),
    question_revision_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> schemas.HumanSubmissionResponse:
    return await service.create_uploaded_submission(
        workspace_id,
        question_revision_id,
        command_id,
        file,
        user,
    )


@router.get(
    "/submissions/{submission_id}",
    response_model=schemas.HumanSubmissionResponse,
    responses=common_errors,
)
def get_submission(
    workspace_id: str = Path(min_length=1),
    submission_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> schemas.HumanSubmissionResponse:
    return service.get_submission(workspace_id, submission_id, user)


@router.post(
    "/submissions/{submission_id}/scores",
    response_model=schemas.HumanScoreResponse,
    status_code=status.HTTP_201_CREATED,
    responses=common_errors,
)
def submit_score(
    payload: schemas.ScoreCreateRequest,
    workspace_id: str = Path(min_length=1),
    submission_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> schemas.HumanScoreResponse:
    return service.submit_score(workspace_id, submission_id, payload, user)


@router.get(
    "/submissions/{submission_id}/scores",
    response_model=schemas.HumanScoreHistoryResponse,
    responses=common_errors,
)
def get_score_history(
    workspace_id: str = Path(min_length=1),
    submission_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> schemas.HumanScoreHistoryResponse:
    return service.get_score_history(workspace_id, submission_id, user)
