"""Backfill authored-question integrity fields after the v2 member bridge."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0011_qrev_integrity"
down_revision: Union[str, None] = "0010_qrev_working_set"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "benchmark_question_revisions" in tables:
        columns = {
            item["name"] for item in sa.inspect(bind).get_columns("benchmark_question_revisions")
        }
        if "contract_revision_id" not in columns:
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
    missing = {"question_revision_number", "question_revision_hash"} - columns
    if not missing:
        return
    with op.batch_alter_table("working_set_members", recreate="always") as batch:
        if "question_revision_number" in missing:
            batch.add_column(sa.Column("question_revision_number", sa.Integer(), nullable=True))
        if "question_revision_hash" in missing:
            batch.add_column(sa.Column("question_revision_hash", sa.String(length=64), nullable=True))
        batch.create_check_constraint(
            "ck_working_set_member_revision_identity",
            "(question_revision_id IS NULL AND question_revision_number IS NULL AND question_revision_hash IS NULL) OR "
            "(question_revision_id IS NOT NULL AND question_revision_number IS NOT NULL AND question_revision_hash IS NOT NULL)",
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "working_set_members" in tables:
        columns = {item["name"] for item in sa.inspect(bind).get_columns("working_set_members")}
        if "question_revision_number" in columns or "question_revision_hash" in columns:
            with op.batch_alter_table("working_set_members", recreate="always") as batch:
                batch.drop_constraint("ck_working_set_member_revision_identity", type_="check")
                if "question_revision_hash" in columns:
                    batch.drop_column("question_revision_hash")
                if "question_revision_number" in columns:
                    batch.drop_column("question_revision_number")
    if "benchmark_question_revisions" in tables:
        columns = {
            item["name"] for item in sa.inspect(bind).get_columns("benchmark_question_revisions")
        }
        if "contract_revision_id" in columns:
            with op.batch_alter_table("benchmark_question_revisions", recreate="always") as batch:
                batch.drop_index("ix_benchmark_question_revision_contract_revision_id")
                batch.drop_constraint("fk_benchmark_question_revision_contract", type_="foreignkey")
                batch.drop_column("contract_revision_id")
