"""Allow a Working Set to reference an immutable authored question revision."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0010_qrev_working_set"
down_revision: Union[str, None] = "0009_rubric_publication"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "benchmark_question_revisions" not in tables:
        return

    revision_columns = {
        item["name"] for item in sa.inspect(bind).get_columns("benchmark_question_revisions")
    }
    if "contract_revision_id" not in revision_columns:
        with op.batch_alter_table("benchmark_question_revisions", recreate="always") as batch:
            batch.add_column(sa.Column("contract_revision_id", sa.String(length=36), nullable=True))
            batch.create_foreign_key(
                "fk_benchmark_question_revision_contract",
                "scenario_contract_revisions",
                ["contract_revision_id"],
                ["id"],
            )
            batch.create_index(
                "ix_benchmark_question_revision_contract_revision_id",
                ["contract_revision_id"],
            )

    if "working_set_members" not in tables:
        return
    columns = {item["name"] for item in sa.inspect(bind).get_columns("working_set_members")}
    if "question_revision_id" in columns:
        return

    # ``task_package_id`` was NOT NULL in v1.  Batch recreation is required
    # for SQLite, which cannot alter that constraint in place.  Existing v1
    # rows remain valid because exactly one of the two source columns is set.
    with op.batch_alter_table("working_set_members", recreate="always") as batch:
        batch.alter_column(
            "task_package_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )
        batch.add_column(sa.Column("question_revision_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("question_revision_number", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("question_revision_hash", sa.String(length=64), nullable=True))
        batch.create_foreign_key(
            "fk_working_set_member_question_revision",
            "benchmark_question_revisions",
            ["question_revision_id"],
            ["id"],
        )
        batch.create_unique_constraint(
            "uq_working_set_member_question_revision",
            ["draft_id", "question_revision_id"],
        )
        batch.create_check_constraint(
            "ck_working_set_member_one_source",
            "(task_package_id IS NOT NULL AND question_revision_id IS NULL) OR "
            "(task_package_id IS NULL AND question_revision_id IS NOT NULL)",
        )
        batch.create_check_constraint(
            "ck_working_set_member_revision_identity",
            "(question_revision_id IS NULL AND question_revision_number IS NULL AND question_revision_hash IS NULL) OR "
            "(question_revision_id IS NOT NULL AND question_revision_number IS NOT NULL AND question_revision_hash IS NOT NULL)",
        )
        batch.create_index("ix_working_set_members_question_revision_id", ["question_revision_id"])


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "working_set_members" in tables:
        columns = {item["name"] for item in sa.inspect(bind).get_columns("working_set_members")}
        if "question_revision_id" in columns:
            with op.batch_alter_table("working_set_members", recreate="always") as batch:
                batch.drop_index("ix_working_set_members_question_revision_id")
                batch.drop_constraint("ck_working_set_member_revision_identity", type_="check")
                batch.drop_constraint("ck_working_set_member_one_source", type_="check")
                batch.drop_constraint("uq_working_set_member_question_revision", type_="unique")
                batch.drop_constraint("fk_working_set_member_question_revision", type_="foreignkey")
                batch.drop_column("question_revision_hash")
                batch.drop_column("question_revision_number")
                batch.drop_column("question_revision_id")
                batch.alter_column(
                    "task_package_id",
                    existing_type=sa.String(length=36),
                    nullable=False,
                )

    if "benchmark_question_revisions" in tables:
        columns = {
            item["name"] for item in sa.inspect(bind).get_columns("benchmark_question_revisions")
        }
        if "contract_revision_id" in columns:
            with op.batch_alter_table("benchmark_question_revisions", recreate="always") as batch:
                batch.drop_index("ix_benchmark_question_revision_contract_revision_id")
                batch.drop_constraint("fk_benchmark_question_revision_contract", type_="foreignkey")
                batch.drop_column("contract_revision_id")
