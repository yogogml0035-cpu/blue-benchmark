from collections.abc import Mapping
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.lib.schemas import ErrorResponse


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = dict(details) if details else None


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Mapping[str, Any] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        error={"code": code, "message": message, "details": details}
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message, exc.details)


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    fields = []
    for item in exc.errors():
        location = [str(part) for part in item.get("loc", []) if part != "body"]
        fields.append({"loc": location, "message": str(item.get("msg", "字段不合法"))})
    return error_response(422, "VALIDATION_ERROR", "请求参数不合法。", {"fields": fields})
