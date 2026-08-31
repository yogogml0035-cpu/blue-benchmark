.PHONY: backend frontend start-all openapi contract-check test typecheck build db-migrate db-check checkpoint-setup ai-smoke worker

BACKEND_PORT ?= 8000
FRONTEND_PORT ?= 3000
BACKEND_URL ?= http://127.0.0.1:$(BACKEND_PORT)

backend:
	uv run --project backend uvicorn app.main:app --app-dir backend --reload --port 8000

frontend:
	pnpm --dir frontend dev

start-all:
	@set -e; \
	cleanup() { \
		status=$$?; \
		trap - INT TERM HUP EXIT; \
		kill "$$api_pid" "$$worker_pid" "$$frontend_pid" 2>/dev/null || true; \
		wait "$$api_pid" "$$worker_pid" "$$frontend_pid" 2>/dev/null || true; \
		case "$$status" in 130|143) status=0 ;; esac; \
		exit "$$status"; \
	}; \
	trap cleanup INT TERM HUP EXIT; \
	echo "Starting API on http://127.0.0.1:$(BACKEND_PORT)"; \
	uv run --project backend uvicorn app.main:app --app-dir backend --reload --port $(BACKEND_PORT) & api_pid=$$!; \
	echo "Starting Worker"; \
	(cd backend && uv run python -m app.lib.operations.worker) & worker_pid=$$!; \
	echo "Starting frontend on http://localhost:$(FRONTEND_PORT)"; \
	BACKEND_URL=$(BACKEND_URL) pnpm --dir frontend exec next dev -p $(FRONTEND_PORT) & frontend_pid=$$!; \
	echo "All services started. Press Ctrl+C to stop all three."; \
	while kill -0 "$$api_pid" 2>/dev/null && kill -0 "$$worker_pid" 2>/dev/null && kill -0 "$$frontend_pid" 2>/dev/null; do \
		sleep 1; \
	done; \
	echo "A service stopped; stopping the other services."; \
	exit 1

openapi:
	cd backend && uv run python -m scripts.export_openapi
	cd frontend && pnpm generate:api

contract-check:
	cd backend && uv run python -m scripts.verify_openapi
	tmpdir=$$(mktemp -d); trap 'rm -rf "$$tmpdir"' EXIT; pnpm --dir frontend exec openapi-typescript ../backend/openapi.json -o "$$tmpdir/generated.ts" >/dev/null; cmp -s frontend/src/lib/api/generated.ts "$$tmpdir/generated.ts" || { echo "frontend API types are stale; run: make openapi"; diff -u frontend/src/lib/api/generated.ts "$$tmpdir/generated.ts" | sed -n '1,120p'; exit 1; }

test:
	cd backend && uv run pytest -q
	cd frontend && pnpm typecheck
	$(MAKE) contract-check

typecheck:
	cd frontend && pnpm typecheck

build:
	cd frontend && pnpm build

db-migrate:
	cd backend && uv run alembic upgrade head

db-check:
	cd backend && uv run python -m scripts.check_schema

checkpoint-setup:
	cd backend && uv run python -m scripts.setup_checkpointer

ai-smoke:
	cd backend && uv run python -m scripts.smoke_ai_provider

worker:
	cd backend && uv run python -m app.lib.operations.worker
