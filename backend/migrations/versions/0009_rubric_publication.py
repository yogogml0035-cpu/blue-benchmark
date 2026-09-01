"""Add mutable rubric drafts and immutable published question revisions."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0009_rubric_publication"
down_revision: Union[str, None] = "0008_authoring_question_prompt"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "benchmark_rubric_drafts" not in tables:
        op.create_table(
            "benchmark_rubric_drafts",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("workspace_id", sa.String(length=36), nullable=False),
            sa.Column("question_draft_id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=64), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("source_question_revision", sa.Integer(), nullable=False),
            sa.Column("source_question_hash", sa.String(length=64), nullable=False),
            sa.Column("rubric_json", sa.JSON(), nullable=True),
            sa.Column("pending_question_json", sa.JSON(), nullable=True),
            sa.Column("command_receipts_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("active_operation_id", sa.String(length=36), nullable=True),
            sa.Column("confirmed_by", sa.String(length=36), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.ForeignKeyConstraint(["question_draft_id"], ["benchmark_question_drafts.id"]),
            sa.ForeignKeyConstraint(["confirmed_by"], ["users.id"]),
            sa.UniqueConstraint("question_draft_id", name="uq_benchmark_rubric_draft_question"),
        )
        op.create_index(
            "ix_benchmark_rubric_drafts_workspace_id",
            "benchmark_rubric_drafts",
            ["workspace_id"],
        )
        op.create_index(
            "ix_benchmark_rubric_drafts_question_draft_id",
            "benchmark_rubric_drafts",
            ["question_draft_id"],
        )
        op.create_index(
            "ix_benchmark_rubric_drafts_status",
            "benchmark_rubric_drafts",
            ["status"],
        )
        op.create_index(
            "ix_benchmark_rubric_draft_workspace_status",
            "benchmark_rubric_drafts",
            ["workspace_id", "status"],
        )
        op.create_index(
            "ix_benchmark_rubric_drafts_active_operation_id",
            "benchmark_rubric_drafts",
            ["active_operation_id"],
        )

    if "benchmark_question_revisions" not in _tables():
        op.create_table(
            "benchmark_question_revisions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("workspace_id", sa.String(length=36), nullable=False),
            sa.Column("question_draft_id", sa.String(length=36), nullable=False),
            sa.Column("revision_number", sa.Integer(), nullable=False),
            sa.Column("source_question_revision", sa.Integer(), nullable=False),
            sa.Column("source_question_hash", sa.String(length=64), nullable=False),
            sa.Column("question_snapshot_json", sa.JSON(), nullable=False),
            sa.Column("reference_answer_text", sa.Text(), nullable=False),
            sa.Column("rubric_json", sa.JSON(), nullable=False),
            sa.Column("pass_threshold", sa.Integer(), nullable=False),
            sa.Column("content_sha256", sa.String(length=64), nullable=False),
            sa.Column("published_by", sa.String(length=36), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.ForeignKeyConstraint(["question_draft_id"], ["benchmark_question_drafts.id"]),
            sa.ForeignKeyConstraint(["published_by"], ["users.id"]),
            sa.UniqueConstraint("question_draft_id", "revision_number", name="uq_benchmark_question_revision_number"),
            sa.UniqueConstraint("question_draft_id", "content_sha256", name="uq_benchmark_question_revision_hash"),
        )
        op.create_index(
            "ix_benchmark_question_revisions_workspace_id",
            "benchmark_question_revisions",
            ["workspace_id"],
        )
        op.create_index(
            "ix_benchmark_question_revision_workspace",
            "benchmark_question_revisions",
            ["workspace_id", "revision_number"],
        )
        op.create_index(
            "ix_benchmark_question_revisions_question_draft_id",
            "benchmark_question_revisions",
            ["question_draft_id"],
        )


def downgrade() -> None:
    tables = _tables()
    if "benchmark_question_revisions" in tables:
        op.drop_table("benchmark_question_revisions")
    if "benchmark_rubric_drafts" in tables:
        op.drop_table("benchmark_rubric_drafts")
