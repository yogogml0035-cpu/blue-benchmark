from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    """M0 keeps exactly one platform administrator.

    ``admin_slot`` is a constant sentinel: its unique constraint makes the
    single-admin invariant enforced by the database, not by application
    checks that can race.

    ``password_generation`` increments on every password change; sessions
    carry the generation they were created under, so a local password reset
    invalidates every existing session without racing concurrent logins.
    """

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("admin_slot", name="uq_users_admin_slot"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    password_generation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    admin_slot: Mapped[str] = mapped_column(String(16), nullable=False, default="primary")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SessionRow(Base):
    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    password_generation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SceneRow(Base):
    __tablename__ = "scenes"
    __table_args__ = (UniqueConstraint("name", name="uq_scene_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SceneCredentialRow(Base):
    """One shared upload credential per scene (1:1 model).

    ``token_plaintext`` persists the issued token so the administrator can
    view and copy it again from the scene page; it is cleared to NULL the
    moment the credential is revoked or replaced. Rows created before the 1:1
    model only carry ``token_hash`` (plaintext was never stored), so they
    remain usable for authentication but cannot be revealed until replaced.
    """

    __tablename__ = "scene_credentials"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_scene_credential_token_hash"),
        Index("ix_scene_credential_active", "scene_id", "revoked_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_plaintext: Mapped[str | None] = mapped_column(Text, nullable=True)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)


class EvalQuestionRow(Base):
    """A single current evaluation question record with six material groups."""

    __tablename__ = "eval_questions"
    __table_args__ = (
        UniqueConstraint("scene_id", "client_case_id", name="uq_eval_question_scene_client_case"),
        Index("ix_eval_question_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), index=True)
    client_case_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    task_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    reference_examples_json: Mapped[list] = mapped_column(JSON, nullable=False)
    bad_cases_json: Mapped[list] = mapped_column(JSON, nullable=False)
    reference_answer: Mapped[str] = mapped_column(Text, nullable=False)
    memory_materials_json: Mapped[list] = mapped_column(JSON, nullable=False)
    criteria_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    criteria_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="generating")
    content_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active_operation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    last_error_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ever_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )


class BatchUploadCommandRow(Base):
    """Idempotency receipt for external batch uploads; never stores payload bodies."""

    __tablename__ = "batch_upload_commands"
    __table_args__ = (
        UniqueConstraint("scene_id", "command_id", name="uq_batch_upload_command"),
        CheckConstraint("status IN ('creating','ready')", name="ck_batch_upload_command_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), index=True)
    credential_id: Mapped[str] = mapped_column(
        ForeignKey("scene_credentials.id", ondelete="SET NULL"), nullable=True
    )
    command_id: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="creating")
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OperationJobRow(Base):
    __tablename__ = "operation_jobs"
    __table_args__ = (
        UniqueConstraint("target_type", "target_id", "business_revision", "command_id", name="uq_operation_target_revision_command"),
        Index("ix_operation_claim", "status", "available_at", "lease_until"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    command_id: Mapped[str] = mapped_column(String(255), nullable=False)
    business_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
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
    operation_job_id: Mapped[str] = mapped_column(
        ForeignKey("operation_jobs.id", ondelete="CASCADE"), index=True
    )
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class QuestionRunThreadRow(Base):
    """Service-owned mapping from a question to its durable agent threads.

    One thread per (question, materials revision) generation round; technical
    retries reuse the thread so the checkpoint can resume. The registry is the
    enumeration source for cross-store deletion (ALL historical threads of a
    question must be cleaned before the business row goes away) — rows are
    therefore kept until cleanup completes and are removed in the final
    business delete transaction. Control data only: no material bodies.
    """

    __tablename__ = "question_run_threads"
    __table_args__ = (
        UniqueConstraint("thread_id", name="uq_question_run_thread_id"),
        Index("ix_question_run_thread_question", "question_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    question_id: Mapped[str] = mapped_column(
        ForeignKey("eval_questions.id", ondelete="CASCADE"), nullable=False
    )
    operation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    thread_id: Mapped[str] = mapped_column(String(120), nullable=False)
    materials_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    materials_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class QuestionRunEventRow(Base):
    """Complete public progress log of one generation operation.

    Persisted BEFORE events reach any browser (SSE reads from here), ordered
    by (operation, attempt, sequence) for idempotent replay and reconnect.
    Stores only authorized public content: no private reasoning, system
    prompts, credentials or raw tool payloads.
    """

    __tablename__ = "question_run_events"
    __table_args__ = (
        UniqueConstraint(
            "operation_id", "attempt_number", "sequence", name="uq_question_run_event_seq"
        ),
        Index("ix_question_run_event_question", "question_id", "sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    question_id: Mapped[str] = mapped_column(
        ForeignKey("eval_questions.id", ondelete="CASCADE"), nullable=False
    )
    operation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(120), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(120), nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
