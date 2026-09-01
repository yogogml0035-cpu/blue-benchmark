from __future__ import annotations

from fastapi import APIRouter, Depends, Path, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.features.auth import service as auth_service
from app.features.auth.repository import UserRecord
from app.features.external_authoring import service
from app.features.external_authoring.schemas import (
    ExternalConnectionCreateRequest,
    ExternalConnectionCreateResponse,
    ExternalConnectionExchangeRequest,
    ExternalConnectionExchangeResponse,
    ExternalConnectionStatusResponse,
    ExternalEvaluationCaseDraftRequest,
    ExternalEvaluationCaseDraftResponse,
)
from app.lib.errors import AppError
from app.lib.schemas import ErrorResponse


router = APIRouter(tags=["external-authoring"])
bearer = HTTPBearer(auto_error=False)
common_errors = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


def external_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> service.ExternalAuthoringPrincipal:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise AppError(401, "EXTERNAL_AUTH_REQUIRED", "请提供外部连接凭证。")
    return service.require_principal(credentials.credentials)


@router.post(
    "/workspaces/{workspace_id}/authoring-connections",
    response_model=ExternalConnectionCreateResponse,
    status_code=status.HTTP_201_CREATED,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def create_connection(
    payload: ExternalConnectionCreateRequest,
    workspace_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> ExternalConnectionCreateResponse:
    return service.create_connection(workspace_id, payload, user)


@router.get(
    "/workspaces/{workspace_id}/authoring-connection",
    response_model=ExternalConnectionStatusResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def get_connection(
    workspace_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> ExternalConnectionStatusResponse:
    return service.get_connection(workspace_id, user)


@router.delete(
    "/workspaces/{workspace_id}/authoring-connections/{connection_id}",
    response_model=ExternalConnectionStatusResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def revoke_connection(
    workspace_id: str = Path(min_length=1),
    connection_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> ExternalConnectionStatusResponse:
    return service.revoke_connection(workspace_id, connection_id, user)


@router.post(
    "/external/authoring-connections/exchange",
    response_model=ExternalConnectionExchangeResponse,
    responses={401: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def exchange_connection(payload: ExternalConnectionExchangeRequest) -> ExternalConnectionExchangeResponse:
    return service.exchange_connection(payload.connection_code)


@router.get(
    "/external/authoring-connection",
    response_model=ExternalConnectionStatusResponse,
    responses={401: {"model": ErrorResponse}},
)
def external_status(principal: service.ExternalAuthoringPrincipal = Depends(external_principal)) -> ExternalConnectionStatusResponse:
    return service.get_external_connection_status(principal)


@router.post(
    "/external/evaluation-case-drafts",
    response_model=ExternalEvaluationCaseDraftResponse,
    status_code=status.HTTP_201_CREATED,
    responses={**common_errors, 413: {"model": ErrorResponse}, 415: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
)
def create_external_draft(
    payload: ExternalEvaluationCaseDraftRequest,
    principal: service.ExternalAuthoringPrincipal = Depends(external_principal),
) -> ExternalEvaluationCaseDraftResponse:
    return service.create_external_draft(principal, payload)
