"""Make upload commands idempotent within a workspace."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0003_upload_command_id"
down_revision: Union[str, None] = "0002_attempt_uniqueness"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("upload_batches")}
    constraints = {
        item.get("name") for item in inspector.get_unique_constraints("upload_batches")
    }
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("upload_batches") as batch_op:
            if "command_id" not in columns:
                batch_op.add_column(sa.Column("command_id", sa.String(length=255), nullable=True))
            if "uq_upload_batch_command" not in constraints:
                batch_op.create_unique_constraint(
                    "uq_upload_batch_command", ["workspace_id", "command_id"]
                )
    else:
        if "command_id" not in columns:
            op.add_column("upload_batches", sa.Column("command_id", sa.String(length=255), nullable=True))
        if "uq_upload_batch_command" not in constraints:
            op.create_unique_constraint(
                "uq_upload_batch_command", "upload_batches", ["workspace_id", "command_id"]
            )


def downgrade() -> None:
    bind = op.get_bind()
    constraints = {
        item.get("name") for item in sa.inspect(bind).get_unique_constraints("upload_batches")
    }
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("upload_batches") as batch_op:
            if "uq_upload_batch_command" in constraints:
                batch_op.drop_constraint("uq_upload_batch_command", type_="unique")
            batch_op.drop_column("command_id")
    else:
        if "uq_upload_batch_command" in constraints:
            op.drop_constraint("uq_upload_batch_command", "upload_batches", type_="unique")
        if "command_id" in {item["name"] for item in sa.inspect(bind).get_columns("upload_batches")}:
            op.drop_column("upload_batches", "command_id")
