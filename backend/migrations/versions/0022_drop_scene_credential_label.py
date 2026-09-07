"""Drop the unused scene credential label column.

The 1:1 credential model has no name input anywhere (web UI, CLI callers
aside from a default, or the upload skill), so ``label`` was always NULL and
the UI only ever showed the「未命名凭证」fallback for it. Remove the dead
column; the downgrade restores it as nullable for symmetry.

Revision ID: 0022_drop_scene_credential_label
Revises: 0021_m0_runtime_messages_threads
Create Date: 2026-09-07
"""

from alembic import op
import sqlalchemy as sa


revision = "0022_drop_scene_credential_label"
down_revision = "0021_m0_runtime_messages_threads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "scene_credentials" not in set(inspector.get_table_names()):
        return
    columns = {item["name"] for item in inspector.get_columns("scene_credentials")}
    if "label" in columns:
        # batch_alter_table keeps this reversible on SQLite too.
        with op.batch_alter_table("scene_credentials") as batch_op:
            batch_op.drop_column("label")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "scene_credentials" not in set(inspector.get_table_names()):
        return
    columns = {item["name"] for item in inspector.get_columns("scene_credentials")}
    if "label" not in columns:
        op.add_column(
            "scene_credentials",
            sa.Column("label", sa.String(length=200), nullable=True),
        )
