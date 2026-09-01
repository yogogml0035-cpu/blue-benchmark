"""Allow immutable scores to target later revisions of the same question."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0014_cross_revision_scoring"
down_revision: Union[str, None] = "0013_human_scoring"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _foreign_key_names(table_name: str) -> set[str | None]:
    return {item.get("name") for item in sa.inspect(op.get_bind()).get_foreign_keys(table_name)}


def _index_names(table_name: str) -> set[str | None]:
    return {item.get("name") for item in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _create_parent_index() -> None:
    bind = op.get_bind()
    kwargs: dict[str, object] = {"unique": True}
    predicate = sa.text("parent_score_id IS NOT NULL")
    if bind.dialect.name == "sqlite":
        kwargs["sqlite_where"] = predicate
    elif bind.dialect.name == "postgresql":
        kwargs["postgresql_where"] = predicate
    op.create_index(
        "uq_human_score_submission_parent",
        "human_scores",
        ["submission_id", "parent_score_id"],
        **kwargs,
    )


def upgrade() -> None:
    bind = op.get_bind()
    if "human_scores" not in set(sa.inspect(bind).get_table_names()):
        return
    names = _foreign_key_names("human_scores")
    if "fk_human_score_submission_revision" in names:
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("human_scores", recreate="always") as batch:
                batch.drop_constraint("fk_human_score_submission_revision", type_="foreignkey")
                batch.create_foreign_key(
                    "fk_human_score_submission",
                    "evaluation_submissions",
                    ["submission_id"],
                    ["id"],
                    ondelete="CASCADE",
                )
                batch.create_foreign_key(
                    "fk_human_score_question_revision",
                    "benchmark_question_revisions",
                    ["question_revision_id"],
                    ["id"],
                    ondelete="CASCADE",
                )
        else:
            # PostgreSQL parent FKs depend on the composite unique index used
            # by the legacy submission/revision FK. Drop the dependent parent
            # FK first; batch recreation tries to drop the unique constraint
            # before the dependent FK and fails with 2BP01.
            op.drop_constraint("fk_human_score_parent_submission", "human_scores", type_="foreignkey")
            op.drop_constraint("fk_human_score_submission_revision", "human_scores", type_="foreignkey")
            op.create_foreign_key(
                "fk_human_score_submission",
                "human_scores",
                "evaluation_submissions",
                ["submission_id"],
                ["id"],
                ondelete="CASCADE",
            )
            op.create_foreign_key(
                "fk_human_score_question_revision",
                "human_scores",
                "benchmark_question_revisions",
                ["question_revision_id"],
                ["id"],
                ondelete="CASCADE",
            )
            op.create_foreign_key(
                "fk_human_score_parent_submission",
                "human_scores",
                "human_scores",
                ["parent_score_id", "submission_id"],
                ["id", "submission_id"],
                ondelete="CASCADE",
            )
    else:
        missing = {
            "fk_human_score_submission",
            "fk_human_score_question_revision",
        } - names
        if missing:
            raise RuntimeError("human_scores has an unknown foreign-key contract")
    if "uq_human_score_submission_parent" not in _index_names("human_scores"):
        _create_parent_index()


def downgrade() -> None:
    bind = op.get_bind()
    if "human_scores" not in set(sa.inspect(bind).get_table_names()):
        return
    names = _foreign_key_names("human_scores")
    if "fk_human_score_submission" not in names:
        return
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("human_scores", recreate="always") as batch:
            batch.drop_constraint("fk_human_score_submission", type_="foreignkey")
            batch.drop_constraint("fk_human_score_question_revision", type_="foreignkey")
            batch.create_foreign_key(
                "fk_human_score_submission_revision",
                "evaluation_submissions",
                ["submission_id", "question_revision_id"],
                ["id", "question_revision_id"],
                ondelete="CASCADE",
            )
    else:
        op.drop_constraint("fk_human_score_parent_submission", "human_scores", type_="foreignkey")
        op.drop_constraint("fk_human_score_submission", "human_scores", type_="foreignkey")
        op.drop_constraint("fk_human_score_question_revision", "human_scores", type_="foreignkey")
        op.create_foreign_key(
            "fk_human_score_submission_revision",
            "human_scores",
            "evaluation_submissions",
            ["submission_id", "question_revision_id"],
            ["id", "question_revision_id"],
            ondelete="CASCADE",
        )
        op.create_foreign_key(
            "fk_human_score_parent_submission",
            "human_scores",
            "human_scores",
            ["parent_score_id", "submission_id"],
            ["id", "submission_id"],
            ondelete="CASCADE",
        )
    if "uq_human_score_submission_parent" in _index_names("human_scores"):
        op.drop_index("uq_human_score_submission_parent", table_name="human_scores")
