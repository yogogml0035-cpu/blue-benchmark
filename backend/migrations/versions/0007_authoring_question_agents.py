"""Persist the per-question authoring Agent checkpoint pointer."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0007_authoring_question_agents"
down_revision: Union[str, None] = "0006_authoring_conversations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "benchmark_question_drafts" not in tables:
        return
    columns = {item["name"] for item in sa.inspect(bind).get_columns("benchmark_question_drafts")}
    if "question_checkpoint_id" not in columns:
        op.add_column(
            "benchmark_question_drafts",
            sa.Column("question_checkpoint_id", sa.String(length=255), nullable=True),
        )
    if "question_question_count" not in columns:
        op.add_column(
            "benchmark_question_drafts",
            sa.Column("question_question_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        )
    if "question_input_revision" not in columns:
        op.add_column(
            "benchmark_question_drafts",
            sa.Column("question_input_revision", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "benchmark_question_drafts" not in tables:
        return
    columns = {item["name"] for item in sa.inspect(bind).get_columns("benchmark_question_drafts")}
    if "question_question_count" in columns:
        op.drop_column("benchmark_question_drafts", "question_question_count")
    if "question_checkpoint_id" in columns:
        op.drop_column("benchmark_question_drafts", "question_checkpoint_id")
    if "question_input_revision" in columns:
        op.drop_column("benchmark_question_drafts", "question_input_revision")
