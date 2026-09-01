from datetime import datetime

from sqlalchemy import CheckConstraint, JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SessionRow(Base):
    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkspaceRow(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CaseRow(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    task_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_json: Mapped[dict] = mapped_column(JSON)
    parsed_text: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str] = mapped_column(String(64), index=True)
    thread_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    draft_revision: Mapped[int] = mapped_column(Integer, default=0)
    pending_question_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    draft_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_error_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    candidate_case_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    generation_attempts: Mapped[int] = mapped_column(Integer, default=0)
    answered_questions_json: Mapped[dict] = mapped_column(JSON, default=dict)
    mode: Mapped[str] = mapped_column(String(64), default="question")


class UploadBatchRow(Base):
    __tablename__ = "upload_batches"
    __table_args__ = (UniqueConstraint("workspace_id", "command_id", name="uq_upload_batch_command"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    task_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    command_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(64), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceFileRow(Base):
    __tablename__ = "evidence_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    upload_batch_id: Mapped[str] = mapped_column(ForeignKey("upload_batches.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    storage_key: Mapped[str] = mapped_column(String(512), unique=True)
    original_name: Mapped[str] = mapped_column(String(512))
    media_type: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    parse_state: Mapped[str] = mapped_column(String(64), index=True)
    parse_error_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    canonical_view_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_member: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FileDispositionRow(Base):
    __tablename__ = "file_dispositions"
    __table_args__ = (UniqueConstraint("evidence_file_id", name="uq_file_disposition_file"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    evidence_file_id: Mapped[str] = mapped_column(ForeignKey("evidence_files.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(64), default="unknown")
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    ignored: Mapped[bool] = mapped_column(Boolean, default=False)
    visibility: Mapped[str] = mapped_column(String(32), default="unconfirmed")
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskPackageRow(Base):
    __tablename__ = "task_packages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    upload_batch_id: Mapped[str] = mapped_column(ForeignKey("upload_batches.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(200))
    evidence_file_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    analysis_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    contract_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("scenario_contract_revisions.id"), nullable=True, index=True
    )
    draft_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    judgment_package_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    initialization_only: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SkillRunEvidenceRow(Base):
    __tablename__ = "skill_run_evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_package_id: Mapped[str] = mapped_column(ForeignKey("task_packages.id", ondelete="CASCADE"), index=True)
    attempt_key: Mapped[str] = mapped_column(String(255))
    evidence_file_id: Mapped[str | None] = mapped_column(ForeignKey("evidence_files.id"), nullable=True)
    role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CoCreationSessionRow(Base):
    __tablename__ = "co_creation_sessions"
    __table_args__ = (
        UniqueConstraint("task_package_id", "kind", "command_id", name="uq_co_creation_session_command"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    task_package_id: Mapped[str] = mapped_column(ForeignKey("task_packages.id", ondelete="CASCADE"), index=True)
    stable_thread_key: Mapped[str] = mapped_column(String(255), unique=True)
    command_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    kind: Mapped[str] = mapped_column(String(64), default="scenario_contract")
    purpose: Mapped[str | None] = mapped_column(String(64), nullable=True)
    initialization_only: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(64), index=True)
    business_revision: Mapped[int] = mapped_column(Integer, default=0)
    current_turn_revision: Mapped[int] = mapped_column(Integer, default=0)
    accepted_checkpoint_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pending_interrupt_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    projection_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    contract_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    confirmation_command_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    continuity_reset_from_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    continuity_reset_to_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    continuity_reset_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_profile_version: Mapped[str] = mapped_column(String(128))
    graph_schema_version: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CoCreationTurnRow(Base):
    __tablename__ = "co_creation_turns"
    __table_args__ = (
        UniqueConstraint("session_id", "turn_revision", name="uq_co_creation_turn_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("co_creation_sessions.id", ondelete="CASCADE"), index=True)
    turn_revision: Mapped[int] = mapped_column(Integer)
    question_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    question_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_command_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    delta_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    base_checkpoint_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    produced_checkpoint_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    result_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ScenarioContractRevisionRow(Base):
    __tablename__ = "scenario_contract_revisions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "revision", name="uq_contract_revision_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), index=True)
    contract_json: Mapped[dict] = mapped_column(JSON)
    source_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("co_creation_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class QuestionRevisionRow(Base):
    __tablename__ = "question_revisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("co_creation_sessions.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    question_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TeacherFeedbackRow(Base):
    __tablename__ = "teacher_feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_package_id: Mapped[str] = mapped_column(ForeignKey("task_packages.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String(64), default="question_only")
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StandardPromotionProposalRow(Base):
    __tablename__ = "standard_promotion_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    source_feedback_id: Mapped[str] = mapped_column(ForeignKey("teacher_feedback.id", ondelete="CASCADE"), index=True)
    proposed_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OperationJobRow(Base):
    __tablename__ = "operation_jobs"
    __table_args__ = (
        UniqueConstraint(
            "target_type",
            "target_id",
            "business_revision",
            "command_id",
            name="uq_operation_target_revision_command",
        ),
        Index("ix_operation_claim", "status", "available_at", "lease_until"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[str] = mapped_column(String(255), index=True)
    command_id: Mapped[str] = mapped_column(String(255))
    business_revision: Mapped[int] = mapped_column(Integer, default=0)
    accepted_checkpoint_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_error_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentRunAttemptRow(Base):
    __tablename__ = "agent_run_attempts"
    __table_args__ = (UniqueConstraint("operation_job_id", "attempt_number", name="uq_agent_attempt_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    operation_job_id: Mapped[str] = mapped_column(ForeignKey("operation_jobs.id", ondelete="CASCADE"), index=True)
    target_type: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[str] = mapped_column(String(255), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    base_checkpoint_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    produced_checkpoint_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    result_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)




class WorkingSetDraftRow(Base):
    __tablename__ = "working_set_drafts"
    __table_args__ = (
        UniqueConstraint("active_key", name="uq_working_set_draft_active_key"),
        Index("ix_working_set_draft_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    base_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    active_key: Mapped[str | None] = mapped_column(String(36), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    contract_revision_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(32), index=True)
    freeze_intent_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    discarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkingSetMemberRow(Base):
    __tablename__ = "working_set_members"
    __table_args__ = (
        UniqueConstraint("draft_id", "task_package_id", name="uq_working_set_member_task"),
        UniqueConstraint("draft_id", "question_revision_id", name="uq_working_set_member_question_revision"),
        CheckConstraint(
            "(task_package_id IS NOT NULL AND question_revision_id IS NULL) OR "
            "(task_package_id IS NULL AND question_revision_id IS NOT NULL)",
            name="ck_working_set_member_one_source",
        ),
        CheckConstraint(
            "(question_revision_id IS NULL AND question_revision_number IS NULL AND question_revision_hash IS NULL) OR "
            "(question_revision_id IS NOT NULL AND question_revision_number IS NOT NULL AND question_revision_hash IS NOT NULL)",
            name="ck_working_set_member_revision_identity",
        ),
        Index("ix_working_set_member_draft_status", "draft_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    draft_id: Mapped[str] = mapped_column(ForeignKey("working_set_drafts.id", ondelete="CASCADE"), index=True)
    task_package_id: Mapped[str | None] = mapped_column(ForeignKey("task_packages.id"), nullable=True, index=True)
    question_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("benchmark_question_revisions.id"), nullable=True, index=True
    )
    task_package_revision: Mapped[int] = mapped_column(Integer)
    question_revision_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    question_revision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contract_revision_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(32), index=True)
    review_status: Mapped[str] = mapped_column(String(32), index=True)
    deterministic_conflicts_json: Mapped[list] = mapped_column(JSON, default=list)
    ai_suggestions_json: Mapped[list] = mapped_column(JSON, default=list)
    teacher_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkingSetCommandRow(Base):
    __tablename__ = "working_set_commands"
    __table_args__ = (UniqueConstraint("draft_id", "command_id", name="uq_working_set_command"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    draft_id: Mapped[str] = mapped_column(ForeignKey("working_set_drafts.id", ondelete="CASCADE"), index=True)
    command_id: Mapped[str] = mapped_column(String(255))
    payload_hash: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ContractImpactReviewRow(Base):
    __tablename__ = "contract_impact_reviews"
    __table_args__ = (
        UniqueConstraint("draft_id", "task_package_id", name="uq_contract_impact_review_task"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    draft_id: Mapped[str] = mapped_column(ForeignKey("working_set_drafts.id", ondelete="CASCADE"), index=True)
    task_package_id: Mapped[str] = mapped_column(ForeignKey("task_packages.id"), index=True)
    from_contract_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    to_contract_revision_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(32), index=True)
    deterministic_conflicts_json: Mapped[list] = mapped_column(JSON, default=list)
    ai_suggestions_json: Mapped[list] = mapped_column(JSON, default=list)
    teacher_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CoverageSnapshotRow(Base):
    __tablename__ = "coverage_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    draft_id: Mapped[str] = mapped_column(ForeignKey("working_set_drafts.id", ondelete="CASCADE"), index=True)
    draft_revision: Mapped[int] = mapped_column(Integer)
    snapshot_json: Mapped[dict] = mapped_column(JSON)
    risk_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_confirmation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvaluationSetVersionRow(Base):
    __tablename__ = "evaluation_set_versions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "version_number", name="uq_evaluation_set_version_number"),
        UniqueConstraint("workspace_id", "freeze_command_id", name="uq_evaluation_set_freeze_command"),
        Index("ix_evaluation_set_version_workspace", "workspace_id", "version_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    draft_id: Mapped[str] = mapped_column(ForeignKey("working_set_drafts.id"), index=True)
    contract_revision_id: Mapped[str] = mapped_column(String(36))
    schema_version: Mapped[str] = mapped_column(String(128))
    freeze_command_id: Mapped[str] = mapped_column(String(255))
    manifest_key: Mapped[str] = mapped_column(String(512), unique=True)
    runtime_key: Mapped[str] = mapped_column(String(512), unique=True)
    judge_key: Mapped[str] = mapped_column(String(512), unique=True)
    provenance_key: Mapped[str] = mapped_column(String(512), unique=True)
    package_key: Mapped[str] = mapped_column(String(512), unique=True)
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    runtime_sha256: Mapped[str] = mapped_column(String(64))
    judge_sha256: Mapped[str] = mapped_column(String(64))
    provenance_sha256: Mapped[str] = mapped_column(String(64))
    overall_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    risk_confirmation_json: Mapped[dict] = mapped_column(JSON, default=dict)
    frozen_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuthoringConversationRow(Base):
    """User-visible authoring aggregate; Agent continuity stays elsewhere."""

    __tablename__ = "authoring_conversations"
    __table_args__ = (
        UniqueConstraint("workspace_id", "command_id", name="uq_authoring_conversation_command"),
        Index("ix_authoring_conversation_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    upload_batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("upload_batches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    task_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_file_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    command_id: Mapped[str] = mapped_column(String(255))
    command_payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(64), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    active_operation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    pending_question_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    command_receipts_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuthoringMessageRow(Base):
    __tablename__ = "authoring_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence", name="uq_authoring_message_sequence"),
        UniqueConstraint("conversation_id", "command_id", name="uq_authoring_message_command"),
        UniqueConstraint("command_id", name="uq_authoring_message_command_global"),
        Index("ix_authoring_message_conversation_sequence", "conversation_id", "sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("authoring_conversations.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(32))
    message_type: Mapped[str] = mapped_column(String(64), default="chat")
    content_text: Mapped[str] = mapped_column(Text)
    attachment_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    question_draft_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    command_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SafeStreamEventRow(Base):
    __tablename__ = "safe_stream_events"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence", name="uq_safe_stream_event_sequence"),
        Index("ix_safe_stream_event_conversation_sequence", "conversation_id", "sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("authoring_conversations.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BenchmarkQuestionDraftRow(Base):
    __tablename__ = "benchmark_question_drafts"
    __table_args__ = (
        UniqueConstraint("conversation_id", "id", name="uq_benchmark_question_draft_conversation_id"),
        Index("ix_benchmark_question_draft_conversation_status", "conversation_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("authoring_conversations.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(64), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    input_json: Mapped[dict] = mapped_column(JSON, default=dict)
    reference_answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_answer_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_file_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    source_refs_json: Mapped[list] = mapped_column(JSON, default=list)
    question_checkpoint_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    question_question_count: Mapped[int] = mapped_column(Integer, default=0)
    question_input_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    question_prompt_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmed_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmed_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_confirmation_command_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RubricDraftRow(Base):
    """Mutable rubric projection tied to one confirmed authoring question."""

    __tablename__ = "benchmark_rubric_drafts"
    __table_args__ = (
        UniqueConstraint("question_draft_id", name="uq_benchmark_rubric_draft_question"),
        Index("ix_benchmark_rubric_draft_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    question_draft_id: Mapped[str] = mapped_column(
        ForeignKey("benchmark_question_drafts.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(64), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    source_question_revision: Mapped[int] = mapped_column(Integer)
    source_question_hash: Mapped[str] = mapped_column(String(64))
    rubric_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    pending_question_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    command_receipts_json: Mapped[dict] = mapped_column(JSON, default=dict)
    active_operation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BenchmarkQuestionRevisionRow(Base):
    """Immutable published snapshot consumed by later scoring work."""

    __tablename__ = "benchmark_question_revisions"
    __table_args__ = (
        UniqueConstraint("question_draft_id", "revision_number", name="uq_benchmark_question_revision_number"),
        UniqueConstraint("question_draft_id", "content_sha256", name="uq_benchmark_question_revision_hash"),
        Index("ix_benchmark_question_revision_workspace", "workspace_id", "revision_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    question_draft_id: Mapped[str] = mapped_column(
        ForeignKey("benchmark_question_drafts.id"), index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer)
    source_question_revision: Mapped[int] = mapped_column(Integer)
    source_question_hash: Mapped[str] = mapped_column(String(64))
    contract_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("scenario_contract_revisions.id"), nullable=True, index=True
    )
    question_snapshot_json: Mapped[dict] = mapped_column(JSON)
    reference_answer_text: Mapped[str] = mapped_column(Text)
    rubric_json: Mapped[dict] = mapped_column(JSON)
    pass_threshold: Mapped[int] = mapped_column(Integer)
    content_sha256: Mapped[str] = mapped_column(String(64))
    published_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
