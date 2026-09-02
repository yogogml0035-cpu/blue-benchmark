"""Scene folder contracts: creation, credential lifecycle, safe status views."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SceneCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1_000)


class SceneView(BaseModel):
    id: str
    name: str
    description: str | None
    created_at: str
    question_count: int
    active_credential_count: int


class SceneListResponse(BaseModel):
    items: list[SceneView]


class SceneCredentialIssueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, max_length=200)


class SceneCredentialIssuedView(BaseModel):
    """Returned exactly once at issue/rotate time; plaintext is never stored."""

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


class SceneStatusResponse(BaseModel):
    scene: SceneView
    credentials: list[SceneCredentialStatusView]
