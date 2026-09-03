"""Destructive M0 migration: drop legacy authoring/scoring tables, create the
unified question library schema.

Revision ID: 0018_m0_question_library
Revises: 0017_external_input_metadata
Create Date: 2026-09-03

Legacy business data is intentionally not migrated. Downgrade restores schema
shapes only; deleted data is not recovered.
"""

from alembic import op
import sqlalchemy as sa


revision = "0018_m0_question_library"
down_revision = "0017_external_input_metadata"
branch_labels = None
depends_on = None


_LEGACY_TABLES = [
    "human_score_items",
    "human_scores",
    "evaluation_submissions",
    "benchmark_question_revisions",
    "benchmark_rubric_drafts",
    "benchmark_question_drafts",
    "safe_stream_events",
    "authoring_messages",
    "authoring_external_commands",
    "authoring_connections",
    "authoring_conversations",
    "evaluation_set_versions",
    "coverage_snapshots",
    "contract_impact_reviews",
    "working_set_commands",
    "working_set_members",
    "working_set_drafts",
    "scenario_contract_revisions",
    "standard_promotion_proposals",
    "teacher_feedback",
    "skill_run_evidence",
    "question_revisions",
    "co_creation_turns",
    "co_creation_sessions",
    "task_packages",
    "file_dispositions",
    "evidence_files",
    "upload_batches",
    "cases",
    "workspaces",
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    for table in _LEGACY_TABLES:
        if table in existing:
            op.drop_table(table)

    # Enforce the single-admin invariant at the database level. A fresh
    # database already has the column (created through the ORM metadata);
    # a legacy-head database is upgraded in place.
    if "users" in existing:
        user_columns = {item["name"] for item in inspector.get_columns("users")}
        if "admin_slot" not in user_columns:
            op.add_column(
                "users", sa.Column("admin_slot", sa.String(length=16), nullable=True)
            )
            op.execute("UPDATE users SET admin_slot = 'primary'")
            # A legacy development database could hold more than one user;
            # keep only the earliest so the unique invariant can be applied.
            op.execute(
                "DELETE FROM users WHERE id NOT IN "
                "(SELECT id FROM users ORDER BY created_at LIMIT 1)"
            )
            existing_constraints = {
                item.get("name") for item in inspector.get_unique_constraints("users")
            }
            existing_indexes = {item.get("name") for item in inspector.get_indexes("users")}
            if "uq_users_admin_slot" not in existing_constraints | existing_indexes:
                op.create_index("uq_users_admin_slot", "users", ["admin_slot"], unique=True)

    # Legacy job history belongs to removed business chains; it is not
    # compatible with the new question library.
    if "agent_run_attempts" in existing:
        op.execute("DELETE FROM agent_run_attempts")
    if "operation_jobs" in existing:
        op.execute("DELETE FROM operation_jobs")

    if "scenes" not in existing:
        op.create_table(
            "scenes",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("name", name="uq_scene_name"),
        )

    if "scene_credentials" not in existing:
        op.create_table(
            "scene_credentials",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "scene_id",
                sa.String(length=36),
                sa.ForeignKey("scenes.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("label", sa.String(length=200), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_reason", sa.String(length=64), nullable=True),
            sa.UniqueConstraint("token_hash", name="uq_scene_credential_token_hash"),
        )
        op.create_index(
            "ix_scene_credential_active", "scene_credentials", ["scene_id", "revoked_at"]
        )
        op.create_index("ix_scene_credential_scene", "scene_credentials", ["scene_id"])

    if "eval_questions" not in existing:
        op.create_table(
            "eval_questions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "scene_id",
                sa.String(length=36),
                sa.ForeignKey("scenes.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("client_case_id", sa.String(length=128), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("task_prompt", sa.Text(), nullable=False),
            sa.Column("reference_examples_json", sa.JSON(), nullable=False),
            sa.Column("bad_cases_json", sa.JSON(), nullable=False),
            sa.Column("reference_answer", sa.Text(), nullable=False),
            sa.Column("memory_materials_json", sa.JSON(), nullable=False),
            sa.Column("criteria_json", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="generating"),
            sa.Column("content_revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("active_operation_id", sa.String(length=36), nullable=True),
            sa.Column("last_error_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "scene_id", "client_case_id", name="uq_eval_question_scene_client_case"
            ),
        )
        op.create_index("ix_eval_question_status", "eval_questions", ["status"])
        op.create_index("ix_eval_question_scene", "eval_questions", ["scene_id"])
        op.create_index(
            "ix_eval_question_active_operation", "eval_questions", ["active_operation_id"]
        )

    if "batch_upload_commands" not in existing:
        op.create_table(
            "batch_upload_commands",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "scene_id",
                sa.String(length=36),
                sa.ForeignKey("scenes.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "credential_id",
                sa.String(length=36),
                sa.ForeignKey("scene_credentials.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("command_id", sa.String(length=255), nullable=False),
            sa.Column("payload_hash", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="creating"),
            sa.Column("result_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("scene_id", "command_id", name="uq_batch_upload_command"),
            sa.CheckConstraint(
                "status IN ('creating','ready')", name="ck_batch_upload_command_status"
            ),
        )
        op.create_index("ix_batch_upload_command_scene", "batch_upload_commands", ["scene_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    for table in [
        "batch_upload_commands",
        "eval_questions",
        "scene_credentials",
        "scenes",
    ]:
        if table in existing:
            op.drop_table(table)

    # Schema-shape-only restoration of the legacy head; no data is recovered.
    # Columns are the minimal business shape, not the full legacy contract.
    def _ensure(name: str, *columns) -> None:
        if name not in sa.inspect(op.get_bind()).get_table_names():
            op.create_table(name, *columns)

    _t = sa.Column("created_at", sa.DateTime(timezone=True), nullable=False)

    _ensure(
        "workspaces",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _ensure(
        "cases",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _ensure(
        "upload_batches",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("command_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _ensure(
        "evidence_files",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("upload_batch_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("external_metadata_json", sa.JSON(), nullable=True),
        _t,
    )
    _ensure(
        "file_dispositions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("evidence_file_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
    )
    _ensure(
        "task_packages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("upload_batch_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
    )
    _ensure(
        "skill_run_evidence",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("task_package_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_key", sa.String(length=255), nullable=False),
    )
    _ensure(
        "co_creation_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("task_package_id", sa.String(length=36), nullable=False),
        sa.Column("command_id", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
    )
    _ensure(
        "co_creation_turns",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("turn_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
    )
    _ensure(
        "scenario_contract_revisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
    )
    _ensure(
        "question_revisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
    )
    _ensure(
        "teacher_feedback",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("task_package_id", sa.String(length=36), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
    )
    _ensure(
        "standard_promotion_proposals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
    )
    _ensure(
        "working_set_drafts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("active_key", sa.String(length=255), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=64), nullable=False),
    )
    _ensure(
        "working_set_members",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("draft_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
    )
    _ensure(
        "working_set_commands",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("draft_id", sa.String(length=36), nullable=False),
        sa.Column("command_id", sa.String(length=255), nullable=False),
    )
    _ensure(
        "contract_impact_reviews",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("draft_id", sa.String(length=36), nullable=False),
        sa.Column("task_package_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
    )
    _ensure(
        "coverage_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("draft_id", sa.String(length=36), nullable=False),
        sa.Column("draft_revision", sa.Integer(), nullable=False),
    )
    _ensure(
        "evaluation_set_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("overall_sha256", sa.String(length=64), nullable=False),
    )
    _ensure(
        "authoring_conversations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("command_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
    )
    _ensure(
        "authoring_messages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
    )
    _ensure(
        "safe_stream_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
    )
    _ensure(
        "authoring_connections",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    _ensure(
        "authoring_external_commands",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("connection_id", sa.String(length=36), nullable=False),
        sa.Column("command_id", sa.String(length=255), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
    )
    _ensure(
        "benchmark_question_drafts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
    )
    _ensure(
        "benchmark_rubric_drafts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("question_draft_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
    )
    _ensure(
        "benchmark_question_revisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("question_draft_id", sa.String(length=36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
    )
    _ensure(
        "evaluation_submissions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("question_revision_id", sa.String(length=36), nullable=False),
        sa.Column("command_id", sa.String(length=255), nullable=False),
    )
    _ensure(
        "human_scores",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("submission_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
    )
    _ensure(
        "human_score_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("score_id", sa.String(length=36), nullable=False),
        sa.Column("criterion_id", sa.String(length=64), nullable=False),
    )
