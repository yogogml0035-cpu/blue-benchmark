"""Prevent duplicate run attempts for one operation."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0002_attempt_uniqueness"
down_revision: Union[str, None] = "0001_initial_business_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = {
        item.get("name")
        for item in sa.inspect(bind).get_unique_constraints("agent_run_attempts")
    }
    if "uq_agent_attempt_number" in existing:
        return
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("agent_run_attempts") as batch_op:
            batch_op.create_unique_constraint("uq_agent_attempt_number", ["operation_job_id", "attempt_number"])
    else:
        op.create_unique_constraint(
            "uq_agent_attempt_number",
            "agent_run_attempts",
            ["operation_job_id", "attempt_number"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing = {
        item.get("name")
        for item in sa.inspect(bind).get_unique_constraints("agent_run_attempts")
    }
    if "uq_agent_attempt_number" not in existing:
        return
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("agent_run_attempts") as batch_op:
            batch_op.drop_constraint("uq_agent_attempt_number", type_="unique")
    else:
        op.drop_constraint("uq_agent_attempt_number", "agent_run_attempts", type_="unique")
