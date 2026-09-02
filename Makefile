.PHONY: backend start-all openapi contract-check test build db-migrate db-check ai-smoke worker admin
BACKEND_PORT ?= 8000

backend:
	uv run --project backend uvicorn app.main:app --app-dir backend --reload --port $(BACKEND_PORT)

start-all:
	@set -e; \
	cleanup() { \
		status=$$?; \
		trap - INT TERM HUP EXIT; \
		kill "$$api_pid" "$$worker_pid" 2>/dev/null || true; \
		wait "$$api_pid" "$$worker_pid" 2>/dev/null || true; \
		case "$$status" in 130|143) status=0 ;; esac; \
		exit "$$status"; \
	}; \
	trap cleanup INT TERM HUP EXIT; \
	echo "Starting API on http://127.0.0.1:$(BACKEND_PORT)"; \
	uv run --project backend uvicorn app.main:app --app-dir backend --reload --port $(BACKEND_PORT) & api_pid=$$!; \
	echo "Starting Worker"; \
	(cd backend && uv run python -m app.lib.operations.worker) & worker_pid=$$!; \
	echo "API + Worker started. Press Ctrl+C to stop both."; \
	while kill -0 "$$api_pid" 2>/dev/null && kill -0 "$$worker_pid" 2>/dev/null; do \
		sleep 1; \
	done; \
	echo "A service stopped; stopping the other service."; \
	exit 1

openapi:
	cd backend && uv run python -m scripts.export_openapi

contract-check:
	cd backend && uv run python -m scripts.verify_openapi

test:
	cd backend && uv run pytest -q
	$(MAKE) contract-check

build:
	cd backend && uv run python -m compileall -q app scripts tests migrations
	cd backend && uv run python -c "import app.main; import app.lib.operations.worker; print('backend import ok')"

db-migrate:
	cd backend && uv run alembic upgrade head

db-check:
	cd backend && uv run python -m scripts.check_schema

ai-smoke:
	cd backend && uv run python -m scripts.smoke_ai_provider

worker:
	cd backend && uv run python -m app.lib.operations.worker

admin:
	@echo "Run the admin CLI directly (arguments are not shell-interpolated here):"
	@echo "  cd backend && uv run python -m scripts.admin_cli --help"
	@cd backend && uv run python -m scripts.admin_cli --help
