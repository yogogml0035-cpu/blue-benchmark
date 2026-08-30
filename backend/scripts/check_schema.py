from app.lib.database import check_schema_ready


if __name__ == "__main__":
    if not check_schema_ready():
        raise SystemExit("business schema is not ready; run: uv run alembic upgrade head")
    print("business schema ready")
