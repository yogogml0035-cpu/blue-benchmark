"""Track the teacher message boundary for a pending question-agent prompt."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0008_authoring_question_prompt"
down_revision: Union[str, None] = "0007_authoring_question_agents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "benchmark_question_drafts" not in tables:
        return
    columns = {item["name"] for item in sa.inspect(bind).get_columns("benchmark_question_drafts")}
    if "question_prompt_sequence" not in columns:
        op.add_column(
            "benchmark_question_drafts",
            sa.Column("question_prompt_sequence", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "benchmark_question_drafts" not in tables:
        return
    columns = {item["name"] for item in sa.inspect(bind).get_columns("benchmark_question_drafts")}
    if "question_prompt_sequence" in columns:
        op.drop_column("benchmark_question_drafts", "question_prompt_sequence")
