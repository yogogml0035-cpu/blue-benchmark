"""Add the database-level authored member identity invariant."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0012_qrev_checks"
down_revision: Union[str, None] = "0011_qrev_integrity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "working_set_members" not in tables:
        return
    constraints = sa.inspect(bind).get_check_constraints("working_set_members")
    if any(item.get("name") == "ck_working_set_member_revision_identity" for item in constraints):
        return
    with op.batch_alter_table("working_set_members", recreate="always") as batch:
        batch.create_check_constraint(
            "ck_working_set_member_revision_identity",
            "(question_revision_id IS NULL AND question_revision_number IS NULL AND question_revision_hash IS NULL) OR "
            "(question_revision_id IS NOT NULL AND question_revision_number IS NOT NULL AND question_revision_hash IS NOT NULL)",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "working_set_members" not in set(sa.inspect(bind).get_table_names()):
        return
    with op.batch_alter_table("working_set_members", recreate="always") as batch:
        batch.drop_constraint("ck_working_set_member_revision_identity", type_="check")
