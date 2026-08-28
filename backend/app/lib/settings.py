from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Skill Eval Platform API"
    frontend_url: str = "http://localhost:3000"
    session_cookie_name: str = "skill_eval_session"
    session_cookie_secure: bool = False
    upload_max_bytes: int = 1_048_576

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

