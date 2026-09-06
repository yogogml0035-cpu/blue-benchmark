.PHONY: backend start-all openapi contract-check test build db-migrate db-check ai-smoke worker admin \
	frontend-install frontend-dev frontend-build frontend-test frontend-typecheck \
	frontend-check-api frontend-generate-api frontend-e2e accept-web reset-local
BACKEND_PORT ?= 8000
FRONTEND_PORT ?= 3000

backend:
	uv run --project backend uvicorn app.main:app --app-dir backend --reload --port $(BACKEND_PORT)

# Start API + exactly one Worker + the Next.js console, and tear all three down
# when any one exits (or on Ctrl+C). The worker process lock guarantees only
# one worker per business database.
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
	echo "Starting Worker (single consumer per business database)"; \
	(cd backend && exec uv run python -m app.lib.operations.worker) & worker_pid=$$!; \
	echo "Starting frontend on http://127.0.0.1:$(FRONTEND_PORT)"; \
	(cd frontend && exec env BACKEND_URL=http://127.0.0.1:$(BACKEND_PORT) pnpm dev --port $(FRONTEND_PORT)) & frontend_pid=$$!; \
	echo "API + Worker + frontend started. Press Ctrl+C to stop all."; \
	while kill -0 "$$api_pid" 2>/dev/null && kill -0 "$$worker_pid" 2>/dev/null && kill -0 "$$frontend_pid" 2>/dev/null; do \
		sleep 1; \
	done; \
	echo "A service stopped; stopping the others."; \
	exit 1

openapi:
	cd backend && uv run python -m scripts.export_openapi

contract-check:
	cd backend && uv run python -m scripts.verify_openapi

test:
	cd backend && uv run pytest -q
	$(MAKE) contract-check
	$(MAKE) frontend-typecheck
	$(MAKE) frontend-test
	$(MAKE) frontend-check-api

build:
	cd backend && uv run python -m compileall -q app scripts tests migrations
	cd backend && uv run python -c "import app.main; import app.lib.operations.worker; print('backend import ok')"
	$(MAKE) frontend-build

db-migrate:
	cd backend && uv run alembic upgrade head

db-check:
	cd backend && uv run python -m scripts.check_schema

ai-smoke:
	cd backend && uv run python -m scripts.smoke_ai_provider

# One-shot local data reset (C5 authority). Dry-run only; execution requires
# the explicit --execute --confirm-targets flags directly on the script.
reset-local:
	cd backend && uv run python -m scripts.reset_local_data --dry-run

worker:
	cd backend && uv run python -m app.lib.operations.worker

admin:
	@echo "Run the admin CLI directly (arguments are not shell-interpolated here):"
	@echo "  cd backend && uv run python -m scripts.admin_cli --help"
	@cd backend && uv run python -m scripts.admin_cli --help

# --- Frontend (Next.js admin console) ---------------------------------------

frontend-install:
	cd frontend && pnpm install

frontend-dev:
	cd frontend && pnpm dev

frontend-build:
	cd frontend && pnpm build

frontend-typecheck:
	cd frontend && pnpm typecheck

frontend-test:
	cd frontend && pnpm test

frontend-check-api:
	cd frontend && pnpm check:api

frontend-generate-api:
	cd frontend && pnpm generate:api

frontend-e2e:
	cd frontend && pnpm test:e2e

# Real-AI web acceptance: isolated DB + port + one production worker + real
# provider; drives the full browser chain and prints M0_WEB_ACCEPTANCE=PASS.
accept-web:
	cd frontend && node scripts/real-acceptance.mjs
