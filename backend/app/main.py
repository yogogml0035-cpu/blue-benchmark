from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.features.auth.router import router as auth_router
from app.features.case_builder.router import router as case_builder_router
from app.features.workspaces.router import router as workspaces_router
from app.lib.errors import AppError, app_error_handler, error_response, validation_error_handler
from app.lib.schemas import HealthResponse
from app.lib.settings import settings


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Feature-first in-memory Stub for the Case Builder walking skeleton.",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)


@app.exception_handler(Exception)
async def unexpected_error_handler(_: Request, __: Exception) -> JSONResponse:
    return error_response(500, "INTERNAL_ERROR", "服务暂时无法完成请求。")


@app.middleware("http")
async def same_origin_guard(request: Request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        allowed = {
            settings.frontend_url.rstrip("/"),
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        }
        if origin and origin.rstrip("/") not in allowed:
            return error_response(403, "FORBIDDEN", "只接受同源请求。")
    return await call_next(request)


@app.get("/healthz", response_model=HealthResponse, tags=["system"])
def healthz() -> HealthResponse:
    return HealthResponse(service=settings.app_name)


app.include_router(auth_router, prefix="/api")
app.include_router(workspaces_router, prefix="/api")
app.include_router(case_builder_router, prefix="/api")
