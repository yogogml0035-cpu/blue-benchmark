from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Skill Eval Platform API"
    frontend_url: str = "http://localhost:3000"
    session_cookie_name: str = "skill_eval_session"
    session_cookie_secure: bool = False
    upload_max_bytes: int = 1_048_576
    database_url: str = f"sqlite:///{Path(__file__).resolve().parents[2] / 'storage' / 'skill-eval.db'}"
    checkpoint_database_url: str = ""
    storage_root: Path = Path(__file__).resolve().parents[2] / "storage"
    operation_lease_seconds: int = 60
    operation_max_attempts: int = 3
    upload_max_files: int = 50
    upload_max_total_bytes: int = 10_485_760
    archive_max_members: int = 50
    archive_max_uncompressed_bytes: int = 20_971_520
    archive_max_depth: int = 1
    archive_max_ratio: int = 100
    database_schema_check_on_startup: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
