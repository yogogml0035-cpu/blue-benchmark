"""Add the user-visible authoring conversation and question draft projections."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0006_authoring_conversations"
down_revision: Union[str, None] = "0005_evaluation_versioning"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "authoring_conversations" not in tables:
        op.create_table(
            "authoring_conversations",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("workspace_id", sa.String(length=36), nullable=False),
            sa.Column("upload_batch_id", sa.String(length=36), nullable=True),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("task_instruction", sa.Text(), nullable=True),
            sa.Column("source_file_ids_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("command_id", sa.String(length=255), nullable=False),
            sa.Column("command_payload_hash", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=64), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("active_operation_id", sa.String(length=36), nullable=True),
            sa.Column("pending_question_json", sa.JSON(), nullable=True),
            sa.Column("command_receipts_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_by", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["upload_batch_id"], ["upload_batches.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.UniqueConstraint("workspace_id", "command_id", name="uq_authoring_conversation_command"),
        )
        op.create_index(
            "ix_authoring_conversation_workspace_id",
            "authoring_conversations",
            ["workspace_id"],
        )
        op.create_index(
            "ix_authoring_conversation_upload_batch_id",
            "authoring_conversations",
            ["upload_batch_id"],
        )
        op.create_index(
            "ix_authoring_conversation_active_operation_id",
            "authoring_conversations",
            ["active_operation_id"],
        )
        op.create_index(
            "ix_authoring_conversation_created_by",
            "authoring_conversations",
            ["created_by"],
        )
        op.create_index(
            "ix_authoring_conversation_status",
            "authoring_conversations",
            ["status"],
        )
        op.create_index(
            "ix_authoring_conversation_workspace_status",
            "authoring_conversations",
            ["workspace_id", "status"],
        )

    tables = _tables()
    if "authoring_messages" not in tables:
        op.create_table(
            "authoring_messages",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("conversation_id", sa.String(length=36), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False),
            sa.Column("message_type", sa.String(length=64), nullable=False, server_default="chat"),
            sa.Column("content_text", sa.Text(), nullable=False),
            sa.Column("attachment_ids_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("question_draft_id", sa.String(length=36), nullable=True),
            sa.Column("command_id", sa.String(length=255), nullable=True),
            sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["conversation_id"], ["authoring_conversations.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("conversation_id", "sequence", name="uq_authoring_message_sequence"),
            sa.UniqueConstraint("conversation_id", "command_id", name="uq_authoring_message_command"),
            sa.UniqueConstraint("command_id", name="uq_authoring_message_command_global"),
        )
        op.create_index(
            "ix_authoring_messages_conversation_id",
            "authoring_messages",
            ["conversation_id"],
        )
        op.create_index(
            "ix_authoring_message_conversation_sequence",
            "authoring_messages",
            ["conversation_id", "sequence"],
        )
        op.create_index(
            "ix_authoring_messages_question_draft_id",
            "authoring_messages",
            ["question_draft_id"],
        )

    tables = _tables()
    if "safe_stream_events" not in tables:
        op.create_table(
            "safe_stream_events",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("conversation_id", sa.String(length=36), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(length=64), nullable=False),
            sa.Column("payload_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["conversation_id"], ["authoring_conversations.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("conversation_id", "sequence", name="uq_safe_stream_event_sequence"),
        )
        op.create_index(
            "ix_safe_stream_events_conversation_id",
            "safe_stream_events",
            ["conversation_id"],
        )
        op.create_index(
            "ix_safe_stream_event_conversation_sequence",
            "safe_stream_events",
            ["conversation_id", "sequence"],
        )

    if "benchmark_question_drafts" not in _tables():
        op.create_table(
            "benchmark_question_drafts",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("conversation_id", sa.String(length=36), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=64), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("input_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("reference_answer_text", sa.Text(), nullable=True),
            sa.Column("reference_answer_source", sa.String(length=64), nullable=True),
            sa.Column("evidence_file_ids_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("source_refs_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("confirmed_revision", sa.Integer(), nullable=True),
            sa.Column("confirmed_hash", sa.String(length=64), nullable=True),
            sa.Column("confirmed_by", sa.String(length=36), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_confirmation_command_id", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["conversation_id"], ["authoring_conversations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["confirmed_by"], ["users.id"]),
            sa.UniqueConstraint("conversation_id", "id", name="uq_benchmark_question_draft_conversation_id"),
        )
        op.create_index(
            "ix_benchmark_question_drafts_conversation_id",
            "benchmark_question_drafts",
            ["conversation_id"],
        )
        op.create_index(
            "ix_benchmark_question_drafts_status",
            "benchmark_question_drafts",
            ["status"],
        )
        op.create_index(
            "ix_benchmark_question_draft_conversation_status",
            "benchmark_question_drafts",
            ["conversation_id", "status"],
        )


def downgrade() -> None:
    tables = _tables()
    if "benchmark_question_drafts" in tables:
        op.drop_table("benchmark_question_drafts")
    if "safe_stream_events" in tables:
        op.drop_table("safe_stream_events")
    if "authoring_messages" in tables:
        op.drop_table("authoring_messages")
    if "authoring_conversations" in tables:
        op.drop_table("authoring_conversations")
