from fastapi import APIRouter, Depends, Path, status

from app.features.auth import service as auth_service
from app.features.auth.repository import UserRecord
from app.features.workspaces import service
from app.features.workspaces.schemas import (
    WorkspaceCreateRequest,
    WorkspaceListResponse,
    WorkspaceResponse,
)
from app.lib.schemas import ErrorResponse


router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED, responses={401: {"model": ErrorResponse}})
def create_workspace(
    payload: WorkspaceCreateRequest,
    user: UserRecord = Depends(auth_service.require_current_user),
) -> WorkspaceResponse:
    return WorkspaceResponse(workspace=service.create(payload, user))


@router.get("", response_model=WorkspaceListResponse, responses={401: {"model": ErrorResponse}})
def list_workspaces(
    user: UserRecord = Depends(auth_service.require_current_user),
) -> WorkspaceListResponse:
    return WorkspaceListResponse(items=service.list_for_user(user))


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_workspace(
    workspace_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> WorkspaceResponse:
    return WorkspaceResponse(workspace=service.get_owned(workspace_id, user))

