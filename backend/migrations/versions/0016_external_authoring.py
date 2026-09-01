"""Add revocable external authoring connections and text input metadata."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0016_external_authoring"
down_revision: Union[str, None] = "0015_question_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_names(table_name: str) -> set[str | None]:
    return {item.get("name") for item in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _column_names(table_name: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "evidence_files" in tables and "external_metadata_json" not in _column_names("evidence_files"):
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("evidence_files", recreate="always") as batch:
                batch.add_column(sa.Column("external_metadata_json", sa.JSON(), nullable=True))
        else:
            op.add_column("evidence_files", sa.Column("external_metadata_json", sa.JSON(), nullable=True))

    if "authoring_connections" not in tables:
        op.create_table(
            "authoring_connections",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("workspace_id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("client_name", sa.String(length=100), nullable=False, server_default="本地 Agent"),
            sa.Column("scope_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("code_hash", sa.String(length=64), nullable=True),
            sa.Column("code_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("code_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("token_hash", sa.String(length=64), nullable=True),
            sa.Column("token_created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_reason", sa.String(length=255), nullable=True),
            sa.Column("active_request_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_request_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("code_hash", name="uq_authoring_connection_code_hash"),
            sa.UniqueConstraint("token_hash", name="uq_authoring_connection_token_hash"),
        )
    connection_indexes = _index_names("authoring_connections")
    if "ix_authoring_connection_workspace" not in connection_indexes:
        op.create_index(
            "ix_authoring_connection_workspace",
            "authoring_connections",
            ["workspace_id", "created_at"],
        )
    if "uq_authoring_connection_active_workspace" not in connection_indexes:
        predicate = sa.text("revoked_at IS NULL")
        kwargs: dict[str, object] = {"unique": True}
        if bind.dialect.name == "sqlite":
            kwargs["sqlite_where"] = predicate
        elif bind.dialect.name == "postgresql":
            kwargs["postgresql_where"] = predicate
        op.create_index(
            "uq_authoring_connection_active_workspace",
            "authoring_connections",
            ["workspace_id"],
            **kwargs,
        )

    if "authoring_external_commands" not in tables:
        op.create_table(
            "authoring_external_commands",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("connection_id", sa.String(length=36), nullable=False),
            sa.Column("command_id", sa.String(length=255), nullable=False),
            sa.Column("payload_hash", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="creating"),
            sa.Column("conversation_id", sa.String(length=36), nullable=True),
            sa.Column("draft_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["connection_id"], ["authoring_connections.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("connection_id", "command_id", name="uq_authoring_external_command"),
        )
    command_indexes = _index_names("authoring_external_commands")
    if "ix_authoring_external_command_connection_status" not in command_indexes:
        op.create_index(
            "ix_authoring_external_command_connection_status",
            "authoring_external_commands",
            ["connection_id", "status"],
        )


def downgrade() -> None:
    # External authoring receipts are security and audit data. Keep them when
    # rolling application code back; a forward-compatible schema is safer than
    # deleting the connection history.
    return
