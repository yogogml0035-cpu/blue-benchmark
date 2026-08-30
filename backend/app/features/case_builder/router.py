from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Path, UploadFile, status

from app.features.auth import service as auth_service
from app.features.auth.repository import UserRecord
from app.features.case_builder import service
from app.features.case_builder import ingestion_service
from app.features.case_builder import cocreation_service
from app.features.case_builder.cocreation_schemas import (
    CoCreationAnswerRequest,
    CoCreationConfirmRequest,
    CoCreationRetryRequest,
    CoCreationResetRequest,
    CoCreationSessionResponse,
    CoCreationStartRequest,
    GroupingConfirmationRequest,
    PromotionCreateRequest,
    PromotionDecisionRequest,
    TaskPackageListResponse,
    TaskPackageResponse,
    TaskPackageWorkspaceListResponse,
)
from app.features.case_builder.ingestion_schemas import (
    FileDispositionRequest,
    RetryOperationRequest,
    StudioProjection,
    UploadBatchResponse,
)
from app.features.case_builder.schemas import AnswerRequest, CaseDetail, ConfirmationRequest
from app.lib.schemas import ErrorResponse


router = APIRouter(prefix="/workspaces/{workspace_id}/cases", tags=["case-builder"])
ingestion_router = APIRouter(prefix="/workspaces/{workspace_id}/upload-batches", tags=["ingestion"])
cocreation_router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["cocreation"])
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


@ingestion_router.post(
    "",
    response_model=UploadBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def create_upload_batch(
    title: Annotated[str, Form(min_length=1, max_length=200)],
    files: Annotated[list[UploadFile], File(min_length=1)],
    workspace_id: str = Path(min_length=1),
    task_description: Annotated[str | None, Form(max_length=10_000)] = None,
    command_id: Annotated[str | None, Form(max_length=255)] = None,
    user: UserRecord = Depends(auth_service.require_current_user),
) -> UploadBatchResponse:
    return await ingestion_service.create_upload_batch(
        workspace_id, title, task_description, files, user, command_id
    )


@ingestion_router.get(
    "/studio",
    response_model=StudioProjection,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_studio(
    workspace_id: str = Path(min_length=1),
    batch_id: str | None = None,
    user: UserRecord = Depends(auth_service.require_current_user),
) -> StudioProjection:
    return ingestion_service.get_studio(workspace_id, user, batch_id)


@ingestion_router.get(
    "/{batch_id}",
    response_model=UploadBatchResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_upload_batch(
    workspace_id: str = Path(min_length=1),
    batch_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> UploadBatchResponse:
    return ingestion_service.get_upload_batch(workspace_id, batch_id, user)


@ingestion_router.post(
    "/{batch_id}/retry",
    response_model=UploadBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def retry_batch_analysis(
    payload: RetryOperationRequest,
    workspace_id: str = Path(min_length=1),
    batch_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> UploadBatchResponse:
    return ingestion_service.retry_batch_analysis(workspace_id, batch_id, payload, user)


@ingestion_router.patch(
    "/{batch_id}/files/{file_id}/disposition",
    response_model=UploadBatchResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def update_file_disposition(
    payload: FileDispositionRequest,
    workspace_id: str = Path(min_length=1),
    batch_id: str = Path(min_length=1),
    file_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> UploadBatchResponse:
    return ingestion_service.update_file_disposition(
        workspace_id, batch_id, file_id, payload, user
    )


@ingestion_router.get(
    "/{batch_id}/task-packages",
    response_model=TaskPackageListResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def list_task_packages(
    workspace_id: str = Path(min_length=1),
    batch_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> TaskPackageListResponse:
    return cocreation_service.list_task_packages(workspace_id, batch_id, user)


@ingestion_router.post(
    "/{batch_id}/task-groups/confirmation",
    response_model=TaskPackageListResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def confirm_task_groups(
    payload: GroupingConfirmationRequest,
    workspace_id: str = Path(min_length=1),
    batch_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> TaskPackageListResponse:
    return cocreation_service.confirm_task_groups(workspace_id, batch_id, payload, user)


@cocreation_router.get(
    "/task-packages",
    response_model=TaskPackageWorkspaceListResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def list_workspace_task_packages(
    workspace_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> TaskPackageWorkspaceListResponse:
    return cocreation_service.list_task_packages_for_workspace(workspace_id, user)


@cocreation_router.get(
    "/task-packages/{task_package_id}",
    response_model=TaskPackageResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_task_package(
    workspace_id: str = Path(min_length=1),
    task_package_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> TaskPackageResponse:
    return cocreation_service.get_task_package(workspace_id, task_package_id, user)


@cocreation_router.post(
    "/task-packages/{task_package_id}/co-creation",
    response_model=CoCreationSessionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def start_cocreation(
    payload: CoCreationStartRequest,
    workspace_id: str = Path(min_length=1),
    task_package_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> CoCreationSessionResponse:
    return cocreation_service.start_cocreation(workspace_id, task_package_id, payload, user)


@cocreation_router.get(
    "/co-creation/{session_id}",
    response_model=CoCreationSessionResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_cocreation(
    workspace_id: str = Path(min_length=1),
    session_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> CoCreationSessionResponse:
    return cocreation_service.get_cocreation(workspace_id, session_id, user)


@cocreation_router.post(
    "/co-creation/{session_id}/answers",
    response_model=CoCreationSessionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def answer_cocreation(
    payload: CoCreationAnswerRequest,
    workspace_id: str = Path(min_length=1),
    session_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> CoCreationSessionResponse:
    return cocreation_service.answer_cocreation(workspace_id, session_id, payload, user)


@cocreation_router.post(
    "/co-creation/{session_id}/retry",
    response_model=CoCreationSessionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def retry_cocreation(
    payload: CoCreationRetryRequest,
    workspace_id: str = Path(min_length=1),
    session_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> CoCreationSessionResponse:
    return cocreation_service.retry_cocreation(workspace_id, session_id, payload, user)


@cocreation_router.post(
    "/co-creation/{session_id}/continuity-reset",
    response_model=CoCreationSessionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def reset_cocreation(
    payload: CoCreationResetRequest,
    workspace_id: str = Path(min_length=1),
    session_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> CoCreationSessionResponse:
    return cocreation_service.reset_cocreation(workspace_id, session_id, payload, user)


@cocreation_router.post(
    "/co-creation/{session_id}/contract-confirmation",
    response_model=CoCreationSessionResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def confirm_contract(
    payload: CoCreationConfirmRequest,
    workspace_id: str = Path(min_length=1),
    session_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> CoCreationSessionResponse:
    return cocreation_service.confirm_contract(workspace_id, session_id, payload, user)


@cocreation_router.post(
    "/co-creation/{session_id}/judgment-confirmation",
    response_model=CoCreationSessionResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def confirm_judgment(
    payload: CoCreationConfirmRequest,
    workspace_id: str = Path(min_length=1),
    session_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> CoCreationSessionResponse:
    return cocreation_service.confirm_judgment(workspace_id, session_id, payload, user)


@cocreation_router.post(
    "/task-packages/{task_package_id}/feedback",
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def create_feedback(
    payload: PromotionCreateRequest,
    workspace_id: str = Path(min_length=1),
    task_package_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> dict[str, Any]:
    return cocreation_service.create_feedback(workspace_id, task_package_id, payload, user)


@cocreation_router.post(
    "/standard-promotions/{proposal_id}/decision",
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def decide_promotion(
    payload: PromotionDecisionRequest,
    workspace_id: str = Path(min_length=1),
    proposal_id: str = Path(min_length=1),
    user: UserRecord = Depends(auth_service.require_current_user),
) -> dict[str, Any]:
    return cocreation_service.decide_promotion(workspace_id, proposal_id, payload, user)
