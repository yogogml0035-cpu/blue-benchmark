from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.features.auth.router import router as auth_router
from app.features.question_library.external_router import router as external_intake_router
from app.features.question_library.router import router as question_library_router
from app.features.scenes.router import router as scenes_router
from app.lib.database import check_schema_ready
from app.lib.errors import AppError, app_error_handler, error_response, validation_error_handler
from app.lib.schemas import HealthResponse
from app.lib.settings import settings


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.database_schema_check_on_startup:
        if not check_schema_ready():
            raise RuntimeError("business schema is not ready; run: make db-migrate")
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    description="Backend service for scene-scoped evaluation question management.",
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


@app.get("/healthz", response_model=HealthResponse, tags=["system"])
def healthz() -> HealthResponse:
    return HealthResponse(service=settings.app_name, ai=settings.ai_runtime_mode)


app.include_router(auth_router, prefix="/api")
app.include_router(scenes_router, prefix="/api")
app.include_router(question_library_router, prefix="/api")
app.include_router(external_intake_router, prefix="/api")
