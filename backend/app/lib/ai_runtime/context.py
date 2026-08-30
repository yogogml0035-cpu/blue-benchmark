from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class AgentRunContext(BaseModel):
    """Trusted, per-run context. It is never written into a Checkpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: str = Field(min_length=1, max_length=255)
    workspace_id: str = Field(min_length=1, max_length=255)
    target_type: str = Field(min_length=1, max_length=64)
    target_id: str = Field(min_length=1, max_length=255)
    thread_key: str = Field(min_length=1, max_length=254)
    business_revision: int = Field(ge=0)
    co_creation_question_count: int = Field(default=0, ge=0)
    teacher_answers: tuple[str, ...] = ()
    evidence_file_ids: tuple[str, ...] = ()
    evidence_scope: str = Field(min_length=1, max_length=255)
    ai_profile_version: str = Field(min_length=1, max_length=128)
    graph_schema_version: str = Field(min_length=1, max_length=128)
    deadline: datetime | None = None

    @property
    def evidence_paths(self) -> tuple[str, ...]:
        return tuple(f"/evidence/{file_id}" for file_id in self.evidence_file_ids)
