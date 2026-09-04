# Production image for the FastAPI backend.
#
# Serves two roles from the same image:
#   api    -> uvicorn app.main:app (default CMD)
#   worker -> python -m app.lib.operations.worker (override the command)
#
# Build from the backend/ directory:
#   docker buildx build --platform linux/amd64 -t skill-eval-api:<tag> backend/

FROM ghcr.io/astral-sh/uv:latest AS uv

FROM python:3.12-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim AS run
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY --from=build /app/.venv ./.venv
COPY app ./app
COPY migrations ./migrations
COPY scripts ./scripts
COPY alembic.ini openapi.json ./
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
# Non-root runtime user; /app/storage is provided by a named volume.
RUN useradd --create-home appuser && mkdir -p /app/storage && chown -R appuser /app
USER appuser
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
