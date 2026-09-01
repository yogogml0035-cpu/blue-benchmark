"""Add immutable external answer submissions and human score history."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0013_human_scoring"
down_revision: Union[str, None] = "0012_qrev_checks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ensure_check_constraint(table_name: str, constraint_name: str, expression: str) -> None:
    bind = op.get_bind()
    names = {
        item.get("name") for item in sa.inspect(bind).get_check_constraints(table_name)
    }
    if constraint_name in names:
        return
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(table_name, recreate="always") as batch:
            batch.create_check_constraint(constraint_name, expression)
    else:
        op.create_check_constraint(constraint_name, table_name, expression)


def _assert_existing_contract(
    table_name: str,
    *,
    unique_constraints: set[str] | None = None,
    check_constraints: set[str] | None = None,
    foreign_keys: set[str] | None = None,
) -> None:
    """Fail closed when 0001 already materialized a newer ORM table.

    The initial migration intentionally creates the metadata available at
    runtime. That means a fresh database may contain these tables before its
    version reaches 0013. Never silently accept a partially-created table:
    either its named contract is present or migration stops for repair.
    """

    inspector = sa.inspect(op.get_bind())
    actual_unique = {
        item.get("name") for item in inspector.get_unique_constraints(table_name)
    }
    actual_checks = {
        item.get("name") for item in inspector.get_check_constraints(table_name)
    }
    actual_foreign = {
        item.get("name") for item in inspector.get_foreign_keys(table_name)
    }
    missing = (
        (unique_constraints or set()) - actual_unique,
        (check_constraints or set()) - actual_checks,
        (foreign_keys or set()) - actual_foreign,
    )
    if any(missing):
        raise RuntimeError(
            f"{table_name} exists without the 0013 contract; missing constraints"
        )


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "benchmark_question_revisions" in tables:
        unique_constraints = {
            item.get("name")
            for item in sa.inspect(bind).get_unique_constraints("benchmark_question_revisions")
        }
        if "uq_benchmark_question_revision_workspace_identity" not in unique_constraints:
            if bind.dialect.name == "sqlite":
                with op.batch_alter_table("benchmark_question_revisions", recreate="always") as batch:
                    batch.create_unique_constraint(
                        "uq_benchmark_question_revision_workspace_identity",
                        ["id", "workspace_id"],
                    )
            else:
                op.create_unique_constraint(
                    "uq_benchmark_question_revision_workspace_identity",
                    "benchmark_question_revisions",
                    ["id", "workspace_id"],
                )
    if "evaluation_submissions" not in tables:
        op.create_table(
            "evaluation_submissions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("workspace_id", sa.String(length=36), nullable=False),
            sa.Column("question_revision_id", sa.String(length=36), nullable=False),
            sa.Column("content_storage_key", sa.String(length=512), nullable=False),
            sa.Column("source", sa.String(length=16), nullable=False),
            sa.Column("original_name", sa.String(length=512), nullable=True),
            sa.Column("media_type", sa.String(length=255), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("sha256", sa.String(length=64), nullable=False),
            sa.Column("command_id", sa.String(length=255), nullable=False),
            sa.Column("payload_hash", sa.String(length=64), nullable=False),
            sa.Column("submitted_by", sa.String(length=36), nullable=False),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["question_revision_id", "workspace_id"],
                ["benchmark_question_revisions.id", "benchmark_question_revisions.workspace_id"],
                name="fk_evaluation_submission_question_revision_workspace",
            ),
            sa.ForeignKeyConstraint(["submitted_by"], ["users.id"]),
            sa.UniqueConstraint("workspace_id", "command_id", name="uq_evaluation_submission_command"),
            sa.UniqueConstraint("content_storage_key", name="uq_evaluation_submission_storage_key"),
            sa.UniqueConstraint("id", "question_revision_id", name="uq_evaluation_submission_revision_identity"),
            sa.CheckConstraint("source IN ('paste', 'file')", name="ck_evaluation_submission_source"),
            sa.CheckConstraint("size_bytes > 0 AND size_bytes <= 1048576", name="ck_evaluation_submission_size"),
            sa.CheckConstraint("length(sha256) = 64", name="ck_evaluation_submission_sha256"),
        )
        op.create_index("ix_evaluation_submissions_workspace_id", "evaluation_submissions", ["workspace_id"])
        op.create_index("ix_evaluation_submissions_question_revision_id", "evaluation_submissions", ["question_revision_id"])
        op.create_index("ix_evaluation_submissions_sha256", "evaluation_submissions", ["sha256"])
        op.create_index("ix_evaluation_submissions_submitted_by", "evaluation_submissions", ["submitted_by"])
        op.create_index("ix_evaluation_submission_workspace_created", "evaluation_submissions", ["workspace_id", "submitted_at"])
    else:
        _assert_existing_contract(
            "evaluation_submissions",
            unique_constraints={
                "uq_evaluation_submission_command",
                "uq_evaluation_submission_storage_key",
                "uq_evaluation_submission_revision_identity",
            },
            check_constraints={
                "ck_evaluation_submission_source",
                "ck_evaluation_submission_size",
                "ck_evaluation_submission_sha256",
            },
            foreign_keys={"fk_evaluation_submission_question_revision_workspace"},
        )

    if "human_scores" not in tables:
        op.create_table(
            "human_scores",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("submission_id", sa.String(length=36), nullable=False),
            sa.Column("question_revision_id", sa.String(length=36), nullable=False),
            sa.Column("parent_score_id", sa.String(length=36), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="submitted"),
            sa.Column("total_score", sa.Integer(), nullable=False),
            sa.Column("critical_passed", sa.Boolean(), nullable=False),
            sa.Column("passed", sa.Boolean(), nullable=False),
            sa.Column("overall_reason", sa.Text(), nullable=True),
            sa.Column("command_id", sa.String(length=255), nullable=False),
            sa.Column("payload_hash", sa.String(length=64), nullable=False),
            sa.Column("scored_by", sa.String(length=36), nullable=False),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["submission_id", "question_revision_id"],
                ["evaluation_submissions.id", "evaluation_submissions.question_revision_id"],
                name="fk_human_score_submission_revision",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["parent_score_id", "submission_id"],
                ["human_scores.id", "human_scores.submission_id"],
                name="fk_human_score_parent_submission",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(["scored_by"], ["users.id"]),
            sa.UniqueConstraint("submission_id", "command_id", name="uq_human_score_command"),
            sa.UniqueConstraint("id", "submission_id", name="uq_human_score_submission_identity"),
            sa.CheckConstraint("status = 'submitted'", name="ck_human_score_status"),
            sa.CheckConstraint("total_score >= 0 AND total_score <= 100", name="ck_human_score_total"),
        )
        op.create_index("ix_human_scores_submission_id", "human_scores", ["submission_id"])
        op.create_index("ix_human_scores_question_revision_id", "human_scores", ["question_revision_id"])
        op.create_index("ix_human_scores_parent_score_id", "human_scores", ["parent_score_id"])
        op.create_index("ix_human_scores_scored_by", "human_scores", ["scored_by"])
        op.create_index("ix_human_score_submission_submitted", "human_scores", ["submission_id", "submitted_at"])
    else:
        _assert_existing_contract(
            "human_scores",
            unique_constraints={
                "uq_human_score_command",
                "uq_human_score_submission_identity",
            },
            check_constraints={"ck_human_score_status", "ck_human_score_total"},
            foreign_keys={"fk_human_score_submission_revision", "fk_human_score_parent_submission"},
        )

    if "human_score_items" not in tables:
        op.create_table(
            "human_score_items",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("score_id", sa.String(length=36), nullable=False),
            sa.Column("criterion_id", sa.String(length=64), nullable=False),
            sa.Column("score", sa.Integer(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("hard_fail_triggered", sa.Boolean(), nullable=True),
            sa.Column("critical_passed", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["score_id"], ["human_scores.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("score_id", "criterion_id", name="uq_human_score_item_criterion"),
            sa.CheckConstraint("score >= 0 AND score <= 100", name="ck_human_score_item_score"),
        )
        op.create_index("ix_human_score_items_score_id", "human_score_items", ["score_id"])
    else:
        # The initial migration creates the then-current metadata on a fresh
        # database. If that metadata already included these tables, 0013 must
        # still bring older generated tables up to the explicit contract.
        _ensure_check_constraint(
            "human_score_items",
            "ck_human_score_item_score",
            "score >= 0 AND score <= 100",
        )
        _assert_existing_contract(
            "human_score_items",
            unique_constraints={"uq_human_score_item_criterion"},
            check_constraints={"ck_human_score_item_score"},
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "human_score_items" in tables:
        op.drop_table("human_score_items")
    if "human_scores" in tables:
        op.drop_table("human_scores")
    if "evaluation_submissions" in tables:
        op.drop_table("evaluation_submissions")
    if "benchmark_question_revisions" in tables:
        unique_constraints = {
            item.get("name")
            for item in sa.inspect(bind).get_unique_constraints("benchmark_question_revisions")
        }
        if "uq_benchmark_question_revision_workspace_identity" in unique_constraints:
            if bind.dialect.name == "sqlite":
                with op.batch_alter_table("benchmark_question_revisions", recreate="always") as batch:
                    batch.drop_constraint(
                        "uq_benchmark_question_revision_workspace_identity",
                        type_="unique",
                    )
            else:
                op.drop_constraint(
                    "uq_benchmark_question_revision_workspace_identity",
                    "benchmark_question_revisions",
                    type_="unique",
                )
