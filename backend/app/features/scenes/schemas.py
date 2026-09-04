"""Scene folder contracts: creation, credential lifecycle, safe status views."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Shared bound for the credential label, enforced by the service so both the
# HTTP route and the admin CLI apply the same limit.
CREDENTIAL_LABEL_MAX_LENGTH = 200


class SceneCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1_000)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("场景名称不能为空白。")
        return stripped

    @field_validator("description")
    @classmethod
    def _description_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class SceneView(BaseModel):
    id: str
    name: str
    description: str | None
    created_at: str
    question_count: int
    active_credential_count: int


class SceneUpdateRequest(BaseModel):
    """Full desired metadata state; the same validation rules as creation.

    The web client always submits both fields together, so ``description=null``
    unambiguously clears the description.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1_000)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("场景名称不能为空白。")
        return stripped

    @field_validator("description")
    @classmethod
    def _description_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class SceneListResponse(BaseModel):
    items: list[SceneView]


class SceneCredentialIssueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, max_length=CREDENTIAL_LABEL_MAX_LENGTH)


class SceneConnectionStatusView(BaseModel):
    """What a scene credential holder may learn about its own connection.

    Never includes the token, token hash, or any other scene's data.
    """

    status: Literal["connected"]
    scene_id: str
    scene_name: str
    credential_id: str
    label: str | None
    last_used_at: str | None


class SceneCredentialIssuedView(BaseModel):
    """Returned once at create/replace time for the handoff convenience.

    Unlike the old model, the plaintext is also persisted so the administrator
    can reveal it later from the scene page.
    """

    credential_id: str
    scene_id: str
    token: str
    created_at: str


class SceneCredentialStatusView(BaseModel):
    credential_id: str
    label: str | None
    status: Literal["active", "revoked"]
    created_at: str
    last_used_at: str | None
    revoked_at: str | None
    revoked_reason: str | None
    # Masked preview derived from the stored plaintext (e.g. ``sep_Ab3d…Xy9z``).
    # ``None`` for legacy credentials whose plaintext was never stored.
    token_preview: str | None


class SceneCredentialPlaintextView(BaseModel):
    """Administrator-only reveal of the scene's current credential.

    Served with ``Cache-Control: no-store``; never part of a listing or status
    response.
    """

    credential_id: str
    token: str


class SceneStatusResponse(BaseModel):
    scene: SceneView
    # 1:1 model: at most one active credential, no revoked history.
    credential: SceneCredentialStatusView | None
