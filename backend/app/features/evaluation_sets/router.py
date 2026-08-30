from __future__ import annotations

from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, Depends, Path, status
from fastapi.responses import StreamingResponse

from app.features.auth import service as auth_service
from app.features.auth.repository import UserRecord
from app.features.evaluation_sets import service
from app.features.evaluation_sets.schemas import (
    BatchImpactReviewRequest,
    CoverageConfirmationRequest,
    CoverageReviewRequest,
    DraftCreateRequest,
    DraftDiscardRequest,
    FreezeAcceptedResponse,
    FreezeRequest,
    ImpactReviewDecisionRequest,
    ManifestResponse,
    MemberMutationRequest,
    VersionListResponse,
    WorkingSetDraftResponse,
)
from app.lib.schemas import ErrorResponse


router = APIRouter(prefix="/workspaces/{workspace_id}/evaluation-sets", tags=["evaluation-sets"])
common_errors = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}


@router.post(
    "/drafts",
    response_model=WorkingSetDraftResponse,
    status_code=status.HTTP_201_CREATED,
    responses=common_errors,
)
def create_draft(
    payload: DraftCreateRequest,
    workspace_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> WorkingSetDraftResponse:
    return service.create_draft(workspace_id, payload, user)


@router.get(
    "/drafts/{draft_id}",
    response_model=WorkingSetDraftResponse,
    responses=common_errors,
)
def get_draft(
    workspace_id: str = Path(min_length=1),
    draft_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> WorkingSetDraftResponse:
    return service.get_draft(workspace_id, draft_id, user)


@router.post(
    "/drafts/{draft_id}/discard",
    response_model=WorkingSetDraftResponse,
    responses=common_errors,
)
def discard_draft(
    payload: DraftDiscardRequest,
    workspace_id: str = Path(min_length=1),
    draft_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> WorkingSetDraftResponse:
    return service.discard_draft(workspace_id, draft_id, payload, user)


@router.post(
    "/drafts/{draft_id}/members",
    response_model=WorkingSetDraftResponse,
    responses=common_errors,
)
def mutate_member(
    payload: MemberMutationRequest,
    workspace_id: str = Path(min_length=1),
    draft_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> WorkingSetDraftResponse:
    return service.mutate_member(workspace_id, draft_id, payload, user)


@router.post(
    "/drafts/{draft_id}/impact-reviews/{task_package_id}",
    response_model=WorkingSetDraftResponse,
    responses=common_errors,
)
def decide_impact(
    payload: ImpactReviewDecisionRequest,
    workspace_id: str = Path(min_length=1),
    draft_id: str = Path(min_length=1),
    task_package_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> WorkingSetDraftResponse:
    return service.decide_impact(workspace_id, draft_id, task_package_id, payload, user)


@router.post(
    "/drafts/{draft_id}/impact-reviews/confirm-no-conflict",
    response_model=WorkingSetDraftResponse,
    responses=common_errors,
)
def confirm_impact_batch(
    payload: BatchImpactReviewRequest,
    workspace_id: str = Path(min_length=1),
    draft_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> WorkingSetDraftResponse:
    return service.confirm_impact_batch(workspace_id, draft_id, payload, user)


@router.post(
    "/drafts/{draft_id}/coverage-review",
    response_model=WorkingSetDraftResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=common_errors,
)
def request_coverage_review(
    payload: CoverageReviewRequest,
    workspace_id: str = Path(min_length=1),
    draft_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> WorkingSetDraftResponse:
    return service.request_coverage_review(workspace_id, draft_id, payload, user)


@router.post(
    "/drafts/{draft_id}/coverage-confirmation",
    response_model=WorkingSetDraftResponse,
    responses=common_errors,
)
def confirm_coverage(
    payload: CoverageConfirmationRequest,
    workspace_id: str = Path(min_length=1),
    draft_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> WorkingSetDraftResponse:
    return service.confirm_coverage(workspace_id, draft_id, payload, user)


@router.post(
    "/drafts/{draft_id}/freeze",
    response_model=FreezeAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=common_errors,
)
def freeze(
    payload: FreezeRequest,
    workspace_id: str = Path(min_length=1),
    draft_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> FreezeAcceptedResponse:
    return service.freeze(workspace_id, draft_id, payload, user)


@router.get(
    "/versions",
    response_model=VersionListResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def list_versions(
    workspace_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> VersionListResponse:
    return service.list_versions(workspace_id, user)


@router.get(
    "/versions/{version_id}/manifest",
    response_model=ManifestResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def get_manifest(
    workspace_id: str = Path(min_length=1),
    version_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> ManifestResponse:
    return service.get_manifest(workspace_id, version_id, user)


@router.get(
    "/versions/{version_id}/download",
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def download_package(
    workspace_id: str = Path(min_length=1),
    version_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> StreamingResponse:
    version, content = service.download_package(workspace_id, version_id, user)
    return StreamingResponse(
        BytesIO(content),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="evaluation-v{version.version_number}.zip"',
            "X-Evaluation-Version-Sha256": version.overall_sha256,
        },
    )
