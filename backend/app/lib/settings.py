from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = "Skill Eval Platform API"
    frontend_url: str = "http://localhost:3000"
    session_cookie_name: str = "skill_eval_session"
    session_cookie_secure: bool = False
    upload_max_bytes: int = 1_048_576
    database_url: str = f"sqlite:///{Path(__file__).resolve().parents[2] / 'storage' / 'skill-eval.db'}"
    checkpoint_database_url: str = ""
    checkpoint_encryption_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("CHECKPOINT_ENCRYPTION_KEY", "LANGGRAPH_AES_KEY"),
    )
    # A real provider is the safe default for the long-running worker.  Tests
    # and local deterministic runs must opt into ``fake`` explicitly.
    ai_runtime_mode: str = "production"
    ai_provider: str = ""
    ai_model: str = ""
    ai_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("AI_API_KEY"),
    )
    ai_base_url: str = ""
    ai_request_timeout_seconds: float = Field(default=180.0, gt=0, le=900)
    ai_max_cocreation_questions: int = Field(default=12, ge=1, le=50)
    ai_model_call_limit: int = 12
    ai_tool_call_limit: int = 40
    ai_model_retries: int = 1
    storage_root: Path = Path(__file__).resolve().parents[2] / "storage"
    operation_lease_seconds: int = 60
    operation_max_attempts: int = 3
    upload_max_files: int = 50
    upload_max_total_bytes: int = 10_485_760
    authoring_connection_code_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    external_authoring_max_payload_bytes: int = Field(default=2_000_000, ge=1024, le=10_485_760)
    external_authoring_max_file_bytes: int = Field(default=1_048_576, ge=1, le=2_000_000)
    external_authoring_max_files: int = Field(default=20, ge=1, le=100)
    external_authoring_max_bad_samples: int = Field(default=20, ge=0, le=100)
    external_authoring_max_concurrent_requests: int = Field(default=2, ge=1, le=10)
    external_authoring_min_request_interval_seconds: float = Field(default=0.5, ge=0, le=60)
    external_authoring_request_lease_seconds: int = Field(default=120, ge=30, le=900)
    archive_max_members: int = 50
    archive_max_uncompressed_bytes: int = 20_971_520
    archive_max_depth: int = 1
    archive_max_ratio: int = 100
    database_schema_check_on_startup: bool = True

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    @field_validator("ai_runtime_mode", mode="before")
    @classmethod
    def normalize_runtime_mode(cls, value: object) -> str:
        return str(value or "").strip().lower()

    @field_validator("ai_provider", mode="before")
    @classmethod
    def normalize_ai_provider(cls, value: object) -> str:
        return str(value or "").strip().lower()

    @field_validator("ai_model", mode="before")
    @classmethod
    def normalize_model_name(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("ai_api_key", mode="before")
    @classmethod
    def normalize_api_key(cls, value: object) -> SecretStr:
        if isinstance(value, SecretStr):
            return SecretStr(value.get_secret_value().strip())
        return SecretStr(str(value or "").strip())

    @field_validator("checkpoint_encryption_key", mode="before")
    @classmethod
    def normalize_checkpoint_key(cls, value: object) -> SecretStr:
        if isinstance(value, SecretStr):
            return SecretStr(value.get_secret_value().strip())
        return SecretStr(str(value or "").strip())

    @field_validator("ai_base_url", mode="before")
    @classmethod
    def normalize_ai_base_url(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("storage_root", mode="after")
    @classmethod
    def resolve_storage_root(cls, value: Path) -> Path:
        expanded = value.expanduser()
        return expanded if expanded.is_absolute() else PROJECT_ROOT / expanded


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
