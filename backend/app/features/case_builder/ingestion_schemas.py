from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


class UploadBatchState(StrEnum):
    received = "received"
    analyzing = "analyzing"
    ready_for_confirmation = "ready_for_confirmation"
    failed = "failed"


class EvidenceParseState(StrEnum):
    pending = "pending"
    parsed = "parsed"
    parse_failed = "parse_failed"
    unsupported = "unsupported"


class EvidenceFileSummary(BaseModel):
    id: str
    original_name: str
    media_type: str
    size_bytes: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64)
    parse_state: EvidenceParseState
    parse_error: str | None = None
    source_member: str | None = None
    role: Literal["unknown", "brief", "runtime", "judge", "provenance"] = "unknown"
    required: bool = False
    ignored: bool = False
    visibility: Literal["unconfirmed", "runtime", "judge", "provenance"] = "unconfirmed"


class ActiveOperation(BaseModel):
    id: str
    kind: Literal[
        "batch_analysis",
        "cocreation_start",
        "cocreation_resume",
        "cocreation_reproject",
        "coverage_review",
        "freeze_package",
    ]
    status: Literal["queued", "running", "failed", "projection_pending"]


class OperationReceipt(BaseModel):
    id: str
    status: Literal["succeeded", "failed", "superseded"]
    message: str
    completed_at: datetime | None = None


class NextActionConfirmFiles(BaseModel):
    kind: Literal["confirm_file_roles"] = "confirm_file_roles"
    label: str = "确认资料用途"


class NextActionWait(BaseModel):
    kind: Literal["wait_for_processing"] = "wait_for_processing"
    label: str = "等待资料整理"


class NextActionRetry(BaseModel):
    kind: Literal["retry_processing"] = "retry_processing"
    label: str = "重试资料整理"


class NextActionNone(BaseModel):
    kind: Literal["none"] = "none"
    label: str = "暂无下一步"


NextAction = Annotated[
    NextActionConfirmFiles | NextActionWait | NextActionRetry | NextActionNone,
    Field(discriminator="kind"),
]


class StudioProjection(BaseModel):
    workspace_id: str
    batch_id: str
    batch_status: UploadBatchState
    files: list[EvidenceFileSummary]
    next_action: NextAction
    active_operation: ActiveOperation | None = None
    latest_receipt: OperationReceipt | None = None
    blocking_issues: list[str] = Field(default_factory=list)


class UploadBatch(BaseModel):
    id: str
    workspace_id: str
    title: str
    task_description: str | None = None
    status: UploadBatchState
    revision: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime
    files: list[EvidenceFileSummary]


class UploadBatchResponse(BaseModel):
    batch: UploadBatch
    studio: StudioProjection


class FileDispositionRequest(BaseModel):
    role: Literal["unknown", "brief", "runtime", "judge", "provenance"]
    required: bool = False
    ignored: bool = False
    visibility: Literal["unconfirmed", "runtime", "judge", "provenance"] = "unconfirmed"
    rationale: str | None = Field(default=None, max_length=2_000)
    batch_revision: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_flags(self):
        if self.required and self.ignored:
            raise ValueError("required and ignored cannot both be true")
        if self.ignored and self.visibility != "unconfirmed":
            raise ValueError("ignored files cannot be assigned to a visible view")
        if self.role == "runtime" and self.visibility not in {"runtime", "unconfirmed"}:
            raise ValueError("runtime files must remain in runtime or unconfirmed visibility")
        return self


class RetryOperationRequest(BaseModel):
    command_id: str = Field(min_length=1, max_length=255)
    batch_revision: int = Field(ge=0)
