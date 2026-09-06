"""M0 durable runtime: run threads registry and complete public event log.

Adds ``question_run_threads`` (service-owned mapping from a question to its
durable agent threads; the enumeration source for cross-store deletion) and
``question_run_events`` (the complete public progress log persisted before
events reach any browser).

Backfill policy: none. Under the approved one-shot cutover the current project
databases are reset and rebuilt (C5); legacy rows keep no runtime history and
no compatibility read path is created.

Revision ID: 0021_m0_runtime_messages_threads
Revises: 0020_credential_one_to_one
Create Date: 2026-09-06
"""

from alembic import op
import sqlalchemy as sa


revision = "0021_m0_runtime_messages_threads"
down_revision = "0020_credential_one_to_one"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # A fresh database already has both tables: migration 0001 creates the
    # whole schema from the ORM metadata. Only a legacy-head database needs
    # the incremental CREATE TABLE path.
    if "question_run_threads" not in existing_tables:
        op.create_table(
            "question_run_threads",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "question_id",
                sa.String(length=36),
                sa.ForeignKey("eval_questions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("operation_id", sa.String(length=36), nullable=False),
            sa.Column("thread_id", sa.String(length=120), nullable=False),
            sa.Column("materials_revision", sa.Integer(), nullable=False),
            sa.Column("materials_fingerprint", sa.String(length=64), nullable=False),
            sa.Column("runtime_fingerprint", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("thread_id", name="uq_question_run_thread_id"),
        )
        op.create_index(
            "ix_question_run_thread_question", "question_run_threads", ["question_id"]
        )
        op.create_index(
            "ix_question_run_threads_operation_id", "question_run_threads", ["operation_id"]
        )

    if "question_run_events" not in existing_tables:
        op.create_table(
            "question_run_events",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "question_id",
                sa.String(length=36),
                sa.ForeignKey("eval_questions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("operation_id", sa.String(length=36), nullable=False),
            sa.Column("thread_id", sa.String(length=120), nullable=False),
            sa.Column("attempt_number", sa.Integer(), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("stage", sa.String(length=120), nullable=True),
            sa.Column("text", sa.Text(), nullable=True),
            sa.Column("tool", sa.String(length=64), nullable=True),
            sa.Column("detail", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "operation_id", "sequence", name="uq_question_run_event_seq"
            ),
        )
        op.create_index(
            "ix_question_run_event_question", "question_run_events", ["question_id", "sequence"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "question_run_events" in existing_tables:
        op.drop_table("question_run_events")
    if "question_run_threads" in existing_tables:
        op.drop_table("question_run_threads")
