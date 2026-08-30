"""Add the durable co-creation projections and contract revisions."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0004_cocreation_contracts"
down_revision: Union[str, None] = "0003_upload_command_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "scenario_contract_revisions" not in inspector.get_table_names():
        op.create_table(
            "scenario_contract_revisions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("workspace_id", sa.String(length=36), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("contract_json", sa.JSON(), nullable=False),
            sa.Column("source_session_id", sa.String(length=36), nullable=True),
            sa.Column("confirmed_by", sa.String(length=36), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_session_id"], ["co_creation_sessions.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["confirmed_by"], ["users.id"]),
            sa.UniqueConstraint("workspace_id", "revision", name="uq_contract_revision_number"),
        )
        op.create_index(
            "ix_scenario_contract_revisions_workspace_id",
            "scenario_contract_revisions",
            ["workspace_id"],
        )
        op.create_index(
            "ix_scenario_contract_revisions_status",
            "scenario_contract_revisions",
            ["status"],
        )
        op.create_index(
            "ix_scenario_contract_revisions_source_session_id",
            "scenario_contract_revisions",
            ["source_session_id"],
        )

    task_columns = _columns("task_packages")
    task_additions = [
        ("analysis_json", sa.JSON(), True, None),
        ("contract_revision_id", sa.String(length=36), True, None),
        ("draft_json", sa.JSON(), True, None),
        ("judgment_package_json", sa.JSON(), True, None),
        ("initialization_only", sa.Boolean(), False, sa.false()),
        ("confirmed_by", sa.String(length=36), True, None),
        ("confirmed_at", sa.DateTime(timezone=True), True, None),
    ]
    if bind.dialect.name == "sqlite":
        missing = [
            sa.Column(name, column_type, nullable=nullable, server_default=server_default)
            for name, column_type, nullable, server_default in task_additions
            if name not in task_columns
        ]
        if missing:
            with op.batch_alter_table("task_packages") as batch_op:
                for column in missing:
                    batch_op.add_column(column)
    else:
        for name, column_type, nullable, server_default in task_additions:
            if name not in task_columns:
                op.add_column(
                    "task_packages",
                    sa.Column(name, column_type, nullable=nullable, server_default=server_default),
                )

    session_columns = _columns("co_creation_sessions")
    session_additions = [
        ("command_id", sa.String(length=255), True, None),
        ("kind", sa.String(length=64), False, sa.text("'scenario_contract'")),
        ("purpose", sa.String(length=64), True, None),
        ("initialization_only", sa.Boolean(), False, sa.false()),
        ("current_turn_revision", sa.Integer(), False, sa.text("0")),
        ("projection_json", sa.JSON(), True, None),
        ("contract_revision_id", sa.String(length=36), True, None),
        ("confirmation_command_id", sa.String(length=255), True, None),
        ("continuity_reset_from_id", sa.String(length=36), True, None),
        ("continuity_reset_to_id", sa.String(length=36), True, None),
        ("continuity_reset_reason", sa.Text(), True, None),
    ]
    if bind.dialect.name == "sqlite":
        missing = [
            sa.Column(name, column_type, nullable=nullable, server_default=server_default)
            for name, column_type, nullable, server_default in session_additions
            if name not in session_columns
        ]
        if missing:
            with op.batch_alter_table("co_creation_sessions") as batch_op:
                for column in missing:
                    batch_op.add_column(column)
                if "command_id" not in session_columns:
                    batch_op.create_unique_constraint("uq_co_creation_session_command", ["command_id"])
    else:
        for name, column_type, nullable, server_default in session_additions:
            if name not in session_columns:
                op.add_column("co_creation_sessions", sa.Column(name, column_type, nullable=nullable, server_default=server_default))

    turn_columns = _columns("co_creation_turns")
    turn_additions = [
        ("question_id", sa.String(length=255), True),
        ("answer_command_id", sa.String(length=255), True),
        ("base_checkpoint_id", sa.String(length=255), True),
        ("produced_checkpoint_id", sa.String(length=255), True),
        ("result_hash", sa.String(length=64), True),
    ]
    if bind.dialect.name == "sqlite":
        missing = [sa.Column(name, column_type, nullable=nullable) for name, column_type, nullable in turn_additions if name not in turn_columns]
        if missing:
            with op.batch_alter_table("co_creation_turns") as batch_op:
                for column in missing:
                    batch_op.add_column(column)
                constraints = {item.get("name") for item in sa.inspect(batch_op.impl.bind).get_unique_constraints("co_creation_turns")}
                if "uq_co_creation_turn_revision" not in constraints:
                    batch_op.create_unique_constraint("uq_co_creation_turn_revision", ["session_id", "turn_revision"])
    else:
        for name, column_type, nullable in turn_additions:
            if name not in turn_columns:
                op.add_column("co_creation_turns", sa.Column(name, column_type, nullable=nullable))
        constraints = {item.get("name") for item in sa.inspect(bind).get_unique_constraints("co_creation_turns")}
        if "uq_co_creation_turn_revision" not in constraints:
            op.create_unique_constraint("uq_co_creation_turn_revision", "co_creation_turns", ["session_id", "turn_revision"])

    if "ix_co_creation_turns_question_id" not in {item["name"] for item in sa.inspect(bind).get_indexes("co_creation_turns")}:
        op.create_index("ix_co_creation_turns_question_id", "co_creation_turns", ["question_id"])
    if bind.dialect.name != "sqlite" and "command_id" not in session_columns:
        op.create_unique_constraint("uq_co_creation_session_command", "co_creation_sessions", ["command_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if "co_creation_turns" in sa.inspect(bind).get_table_names():
        constraints = {item.get("name") for item in sa.inspect(bind).get_unique_constraints("co_creation_turns")}
        if "uq_co_creation_turn_revision" in constraints:
            if bind.dialect.name == "sqlite":
                with op.batch_alter_table("co_creation_turns") as batch_op:
                    batch_op.drop_constraint("uq_co_creation_turn_revision", type_="unique")
            else:
                op.drop_constraint("uq_co_creation_turn_revision", "co_creation_turns", type_="unique")
        indexes = {item["name"] for item in sa.inspect(bind).get_indexes("co_creation_turns")}
        if "ix_co_creation_turns_question_id" in indexes:
            op.drop_index("ix_co_creation_turns_question_id", table_name="co_creation_turns")
    if "uq_co_creation_session_command" in {
        item.get("name") for item in sa.inspect(bind).get_unique_constraints("co_creation_sessions")
    }:
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("co_creation_sessions") as batch_op:
                batch_op.drop_constraint("uq_co_creation_session_command", type_="unique")
        else:
            op.drop_constraint("uq_co_creation_session_command", "co_creation_sessions", type_="unique")
    drops = {
        "task_packages": {"analysis_json", "contract_revision_id", "draft_json", "judgment_package_json", "initialization_only", "confirmed_by", "confirmed_at"},
        "co_creation_sessions": {"command_id", "kind", "purpose", "initialization_only", "current_turn_revision", "projection_json", "contract_revision_id", "confirmation_command_id", "continuity_reset_from_id", "continuity_reset_to_id", "continuity_reset_reason"},
        "co_creation_turns": {"question_id", "answer_command_id", "base_checkpoint_id", "produced_checkpoint_id", "result_hash"},
    }
    for table, index_names in {
        "task_packages": {"ix_task_packages_contract_revision_id"},
        "co_creation_sessions": {"ix_co_creation_sessions_contract_revision_id"},
    }.items():
        existing_indexes = {item["name"] for item in sa.inspect(bind).get_indexes(table)}
        for index_name in index_names & existing_indexes:
            op.drop_index(index_name, table_name=table)
    for table, columns in drops.items():
        present = _columns(table)
        names = [name for name in columns if name in present]
        if not names:
            continue
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table(table) as batch_op:
                for name in names:
                    batch_op.drop_column(name)
        else:
            for name in names:
                op.drop_column(table, name)
    if "scenario_contract_revisions" in sa.inspect(bind).get_table_names():
        op.drop_table("scenario_contract_revisions")
