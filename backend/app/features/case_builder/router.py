from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Path, UploadFile, status

from app.features.auth import service as auth_service
from app.features.auth.repository import UserRecord
from app.features.case_builder import service
from app.features.case_builder.schemas import AnswerRequest, CaseDetail, ConfirmationRequest
from app.lib.schemas import ErrorResponse


router = APIRouter(prefix="/workspaces/{workspace_id}/cases", tags=["case-builder"])
common_errors = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}


@router.post("", response_model=CaseDetail, status_code=status.HTTP_201_CREATED, responses={**common_errors, 413: {"model": ErrorResponse}, 415: {"model": ErrorResponse}})
async def create_case(
    title: Annotated[str, Form(min_length=1, max_length=200)],
    file: UploadFile = File(...),
    workspace_id: str = Path(min_length=1),
    task_description: Annotated[str | None, Form(max_length=10_000)] = None,
    user: UserRecord = Depends(auth_service.require_current_user),
) -> CaseDetail:
    return await service.create_case(workspace_id, title, task_description, file, user)


@router.get("/{case_id}", response_model=CaseDetail, responses=common_errors)
def get_case(
    workspace_id: str = Path(min_length=1),
    case_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> CaseDetail:
    return service.get_case(workspace_id, case_id, user)


@router.post("/{case_id}/draft-generation", response_model=CaseDetail, responses=common_errors)
def generate_draft(
    workspace_id: str = Path(min_length=1),
    case_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> CaseDetail:
    return service.generate_draft(workspace_id, case_id, user)


@router.post("/{case_id}/answers", response_model=CaseDetail, responses={**common_errors, 422: {"model": ErrorResponse}})
def answer_question(
    payload: AnswerRequest,
    workspace_id: str = Path(min_length=1),
    case_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> CaseDetail:
    return service.answer_question(workspace_id, case_id, payload, user)


@router.post("/{case_id}/confirmation", response_model=CaseDetail, responses={**common_errors, 422: {"model": ErrorResponse}})
def confirm(
    payload: ConfirmationRequest,
    workspace_id: str = Path(min_length=1),
    case_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> CaseDetail:
    return service.confirm(workspace_id, case_id, payload, user)
