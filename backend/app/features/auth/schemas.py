from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# Single source of truth for admin password bounds; the HTTP register contract
# and the local password-reset CLI both validate against these limits.
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128


class BootstrapResponse(BaseModel):
    """Anonymous first-run probe; reveals only whether registration is open."""

    registration_available: bool


class User(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    email: EmailStr | None = None
    created_at: datetime


class RegisterRequest(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    email: EmailStr | None = None
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("username", mode="before")
    @classmethod
    def trim_username(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("identifier", mode="before")
    @classmethod
    def trim_identifier(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class UserResponse(BaseModel):
    user: User

