.PHONY: backend frontend openapi contract-check test typecheck build db-migrate db-check checkpoint-setup ai-smoke worker

backend:
	uv run --project backend uvicorn app.main:app --app-dir backend --reload --port 8000

frontend:
	pnpm --dir frontend dev

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
