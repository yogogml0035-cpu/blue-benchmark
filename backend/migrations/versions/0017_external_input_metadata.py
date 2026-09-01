"""Ensure evidence rows carry external text-input provenance metadata."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0017_external_input_metadata"
down_revision: Union[str, None] = "0016_external_authoring"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "evidence_files" not in inspector.get_table_names():
        return
    columns = {item["name"] for item in inspector.get_columns("evidence_files")}
    if "external_metadata_json" in columns:
        return
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("evidence_files", recreate="always") as batch:
            batch.add_column(sa.Column("external_metadata_json", sa.JSON(), nullable=True))
    else:
        op.add_column("evidence_files", sa.Column("external_metadata_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    return
