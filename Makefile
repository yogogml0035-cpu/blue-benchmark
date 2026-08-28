.PHONY: backend frontend openapi test typecheck build

backend:
	uv run --project backend uvicorn app.main:app --app-dir backend --reload --port 8000

frontend:
	pnpm --dir frontend dev

openapi:
	cd backend && uv run python -m scripts.export_openapi
	cd frontend && pnpm generate:api

test:
	cd backend && uv run pytest -q
	cd frontend && pnpm typecheck

typecheck:
	cd frontend && pnpm typecheck

build:
	cd frontend && pnpm build

