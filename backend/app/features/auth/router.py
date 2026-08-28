from fastapi import APIRouter, Depends, Request, Response, status

from app.features.auth import service
from app.features.auth.schemas import LoginRequest, RegisterRequest, UserResponse
from app.lib.schemas import ErrorResponse


router = APIRouter(prefix="/auth", tags=["auth"])
error_responses = {401: {"model": ErrorResponse}, 409: {"model": ErrorResponse}}


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses,
)
def register(payload: RegisterRequest, request: Request, response: Response) -> UserResponse:
    if service.optional_current_user(request):
        from app.lib.errors import AppError

        raise AppError(409, "ALREADY_AUTHENTICATED", "当前会话已经登录。")
    return UserResponse(user=service.register(payload, response))


@router.post("/login", response_model=UserResponse, responses=error_responses)
def login(payload: LoginRequest, request: Request, response: Response) -> UserResponse:
    if service.optional_current_user(request):
        from app.lib.errors import AppError

        raise AppError(409, "ALREADY_AUTHENTICATED", "当前会话已经登录。")
    return UserResponse(user=service.login(payload, response))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, responses={403: {"model": ErrorResponse}})
def logout(request: Request, response: Response) -> None:
    service.logout(request, response)


@router.get("/me", response_model=UserResponse, responses={401: {"model": ErrorResponse}})
def me(request: Request) -> UserResponse:
    return UserResponse(user=service.to_user(service.require_current_user(request)))

