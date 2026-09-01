from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.features.auth.router import router as auth_router
from app.features.case_builder.router import (
    cocreation_router,
    ingestion_router,
    router as case_builder_router,
)
from app.features.case_builder.authoring_router import router as authoring_router
from app.features.workspaces.router import router as workspaces_router
from app.features.evaluation_sets.router import router as evaluation_sets_router
from app.features.evaluation_sets.rubric_router import router as rubric_router
from app.lib.errors import AppError, app_error_handler, error_response, validation_error_handler
from app.lib.database import check_schema_ready
from app.lib.schemas import HealthResponse
from app.lib.settings import settings


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.database_schema_check_on_startup and not check_schema_ready():
        raise RuntimeError("business schema is not ready; run: make db-migrate")
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Feature-first FastAPI service for the Skill Eval Platform.",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
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
    return HealthResponse(service=settings.app_name, ai=settings.ai_runtime_mode)


app.include_router(auth_router, prefix="/api")
app.include_router(workspaces_router, prefix="/api")
app.include_router(case_builder_router, prefix="/api")
app.include_router(ingestion_router, prefix="/api")
app.include_router(cocreation_router, prefix="/api")
app.include_router(authoring_router, prefix="/api")
app.include_router(evaluation_sets_router, prefix="/api")
app.include_router(rubric_router, prefix="/api")
