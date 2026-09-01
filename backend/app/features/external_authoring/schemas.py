from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Scope = Literal["connection:read", "draft:create"]


class ExternalConnectionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_name: str = Field(default="本地 Agent", min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_client_name(self) -> "ExternalConnectionCreateRequest":
        if not self.client_name.strip():
            raise ValueError("client_name must not be blank")
        return self


class ExternalConnectionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    client_name: str
    status: Literal["pending_exchange", "active", "expired", "revoked"]
    scopes: list[Scope]
    workspace_name: str
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class ExternalConnectionStatusResponse(BaseModel):
    connection: ExternalConnectionView | None = None


class ExternalConnectionCreateResponse(BaseModel):
    connection: ExternalConnectionView
    connection_code: str
    expires_at: datetime
    exchange_url: str


class ExternalConnectionExchangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_code: str = Field(min_length=20, max_length=200)


class ExternalConnectionExchangeResponse(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    connection: ExternalConnectionView


class ExternalInputFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_file_id: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=512)
    media_type: Literal["text/plain", "text/markdown"]
    content_mode: Literal["full", "teacher_confirmed_excerpt"]
    content_text: str = Field(min_length=1, max_length=1_048_576)
    source_file_name: str | None = Field(default=None, max_length=512)
    excerpt_marker: str | None = Field(default=None, max_length=2_000)
    source_size_bytes: int | None = Field(default=None, ge=0, le=10_485_760)
    source_sha256: str | None = Field(default=None, min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_file(self) -> "ExternalInputFile":
        if not self.display_name.strip() or "\x00" in self.display_name:
            raise ValueError("display_name must be a safe non-empty name")
        if "/" in self.display_name or "\\" in self.display_name or ":" in self.display_name or self.display_name in {".", ".."}:
            raise ValueError("display_name must not contain a path")
        if "\x00" in self.content_text or not self.content_text.strip():
            raise ValueError("content_text must be non-empty UTF-8 text")
        self.content_text.encode("utf-8")
        extension = self.display_name.rsplit(".", 1)[-1].casefold() if "." in self.display_name else ""
        expected = "text/markdown" if extension == "md" else "text/plain" if extension == "txt" else None
        if expected != self.media_type:
            raise ValueError("media_type must match a .txt or .md display_name")
        if self.content_mode == "full":
            if self.source_size_bytes is None or self.source_sha256 is None:
                raise ValueError("full input files must include source size and sha256")
            import hashlib

            content_bytes = self.content_text.encode("utf-8")
            if self.source_size_bytes != len(content_bytes) or self.source_sha256 != hashlib.sha256(content_bytes).hexdigest():
                raise ValueError("full input file content was truncated or changed")
        elif not self.source_file_name or not self.excerpt_marker or not self.source_file_name.strip() or not self.excerpt_marker.strip():
            raise ValueError("teacher_confirmed_excerpt requires source_file_name and excerpt_marker")
        if self.source_file_name and (
            "/" in self.source_file_name
            or "\\" in self.source_file_name
            or self.source_file_name.startswith(("/", "\\"))
            or "file://" in self.source_file_name.casefold()
        ):
            raise ValueError("source_file_name must be a display name, not a host path")
        if self.source_sha256 is not None and any(char not in "0123456789abcdefABCDEF" for char in self.source_sha256):
            raise ValueError("source_sha256 must be hexadecimal")
        return self


class ExternalBadSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    source_ref: str = Field(min_length=1, max_length=500)
    content_text: str = Field(min_length=1, max_length=50_000)
    teacher_feedback_texts: list[str] = Field(min_length=1, max_length=20)
    reason_summary: str = Field(min_length=1, max_length=2_000)


class ExternalEvaluationCaseDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    command_id: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=200)
    task_requirement: str = Field(min_length=1, max_length=10_000)
    input_files: list[ExternalInputFile] = Field(default_factory=list, max_length=20)
    bad_samples: list[ExternalBadSample] = Field(default_factory=list, max_length=20)
    reference_answer_text: str = Field(min_length=1, max_length=50_000)

    @model_validator(mode="after")
    def validate_unique_and_required_text(self) -> "ExternalEvaluationCaseDraftRequest":
        if not self.command_id.strip() or not self.title.strip() or not self.task_requirement.strip() or not self.reference_answer_text.strip():
            raise ValueError("command_id, title, task_requirement, and reference_answer_text are required")
        file_ids = [item.client_file_id for item in self.input_files]
        if len(file_ids) != len(set(file_ids)):
            raise ValueError("input file IDs must be unique")
        sample_ids = [item.id for item in self.bad_samples]
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("bad sample IDs must be unique")
        return self


class ExternalEvaluationCaseDraftResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str
    conversation_id: str
    status: Literal["draft_ready"]
    workspace_name: str
    draft_url: str
