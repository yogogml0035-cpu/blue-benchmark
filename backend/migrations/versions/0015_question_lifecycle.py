"""Add question lifecycle, bad samples, and automatic-version compatibility."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0015_question_lifecycle"
down_revision: Union[str, None] = "0014_cross_revision_scoring"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table_name: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "benchmark_question_drafts" in tables:
        columns = _columns("benchmark_question_drafts")
        missing = {"bad_samples_json", "lifecycle_status", "active_revision_id", "lifecycle_receipts_json", "lifecycle_pending_json"} - columns
        if missing:
            if bind.dialect.name == "sqlite":
                alter = op.batch_alter_table("benchmark_question_drafts", recreate="always")
            else:
                alter = None
            if alter is not None:
                with alter as batch:
                    if "bad_samples_json" not in columns:
                        batch.add_column(sa.Column("bad_samples_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
                    if "lifecycle_status" not in columns:
                        batch.add_column(sa.Column("lifecycle_status", sa.String(length=32), nullable=False, server_default="draft"))
                    if "active_revision_id" not in columns:
                        batch.add_column(sa.Column("active_revision_id", sa.String(length=36), nullable=True))
                    if "lifecycle_receipts_json" not in columns:
                        batch.add_column(sa.Column("lifecycle_receipts_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
                    if "lifecycle_pending_json" not in columns:
                        batch.add_column(sa.Column("lifecycle_pending_json", sa.JSON(), nullable=True))
                    if "lifecycle_status" not in columns:
                        batch.create_index("ix_benchmark_question_draft_lifecycle_status", ["lifecycle_status"])
                    if "active_revision_id" not in columns:
                        batch.create_index("ix_benchmark_question_draft_active_revision_id", ["active_revision_id"])
            else:
                if "bad_samples_json" not in columns:
                    op.add_column("benchmark_question_drafts", sa.Column("bad_samples_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
                if "lifecycle_status" not in columns:
                    op.add_column("benchmark_question_drafts", sa.Column("lifecycle_status", sa.String(length=32), nullable=False, server_default="draft"))
                if "active_revision_id" not in columns:
                    op.add_column("benchmark_question_drafts", sa.Column("active_revision_id", sa.String(length=36), nullable=True))
                if "lifecycle_receipts_json" not in columns:
                    op.add_column("benchmark_question_drafts", sa.Column("lifecycle_receipts_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
                if "lifecycle_pending_json" not in columns:
                    op.add_column("benchmark_question_drafts", sa.Column("lifecycle_pending_json", sa.JSON(), nullable=True))
                indexes = {item.get("name") for item in sa.inspect(bind).get_indexes("benchmark_question_drafts")}
                if "lifecycle_status" not in columns:
                    if "ix_benchmark_question_draft_lifecycle_status" not in indexes:
                        op.create_index("ix_benchmark_question_draft_lifecycle_status", "benchmark_question_drafts", ["lifecycle_status"])
                if "active_revision_id" not in columns:
                    if "ix_benchmark_question_draft_active_revision_id" not in indexes:
                        op.create_index("ix_benchmark_question_draft_active_revision_id", "benchmark_question_drafts", ["active_revision_id"])
    if "benchmark_question_revisions" in tables:
        columns = _columns("benchmark_question_revisions")
        missing = {"bad_samples_json", "publication_status"} - columns
        if missing:
            if bind.dialect.name == "sqlite":
                alter = op.batch_alter_table("benchmark_question_revisions", recreate="always")
            else:
                alter = None
            if alter is not None:
                with alter as batch:
                    if "bad_samples_json" not in columns:
                        batch.add_column(sa.Column("bad_samples_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
                    if "publication_status" not in columns:
                        batch.add_column(sa.Column("publication_status", sa.String(length=32), nullable=False, server_default="published"))
                    if "publication_status" not in columns:
                        batch.create_index("ix_benchmark_question_revision_publication_status", ["publication_status"])
            else:
                if "bad_samples_json" not in columns:
                    op.add_column("benchmark_question_revisions", sa.Column("bad_samples_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
                if "publication_status" not in columns:
                    op.add_column("benchmark_question_revisions", sa.Column("publication_status", sa.String(length=32), nullable=False, server_default="published"))
                indexes = {item.get("name") for item in sa.inspect(bind).get_indexes("benchmark_question_revisions")}
                if "publication_status" not in columns:
                    if "ix_benchmark_question_revision_publication_status" not in indexes:
                        op.create_index("ix_benchmark_question_revision_publication_status", "benchmark_question_revisions", ["publication_status"])
    if "evaluation_set_versions" in tables:
        columns = _columns("evaluation_set_versions")
        if "draft_id" in columns and bind.dialect.name == "sqlite":
            with op.batch_alter_table("evaluation_set_versions", recreate="always") as batch:
                batch.alter_column("draft_id", existing_type=sa.String(length=36), nullable=True)
                batch.alter_column("contract_revision_id", existing_type=sa.String(length=36), nullable=True)
        elif "draft_id" in columns:
            op.alter_column("evaluation_set_versions", "draft_id", existing_type=sa.String(length=36), nullable=True)
            op.alter_column("evaluation_set_versions", "contract_revision_id", existing_type=sa.String(length=36), nullable=True)
    if {"benchmark_question_drafts", "benchmark_question_revisions"}.issubset(tables):
        bind.execute(
            sa.text(
                "UPDATE benchmark_question_drafts "
                "SET lifecycle_status = 'active', "
                "active_revision_id = (SELECT id FROM benchmark_question_revisions "
                "WHERE question_draft_id = benchmark_question_drafts.id "
                "AND publication_status = 'published' "
                "ORDER BY revision_number DESC LIMIT 1) "
                "WHERE lifecycle_status = 'draft' "
                "AND EXISTS (SELECT 1 FROM benchmark_question_revisions "
                "WHERE question_draft_id = benchmark_question_drafts.id "
                "AND publication_status = 'published')"
            )
        )


def downgrade() -> None:
    # Lifecycle data is forward-only; do not delete historical rows during a
    # downgrade. Roll back the application with a compatible schema instead.
    return
