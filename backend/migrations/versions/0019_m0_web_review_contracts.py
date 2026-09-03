"""M0 web review contracts: teacher confirmation and publish-history facts.

Adds ``criteria_confirmed`` (the rubric was saved by the teacher, not just
drafted by the AI) and ``ever_published`` (the question was published at least
once, so deletion keeps its stronger confirmation gate) to ``eval_questions``.

Backfill policy:
- questions already ``published`` were necessarily reviewed under the old
  contract, so both facts are true;
- every other historical question starts unconfirmed and never-published, so
  the teacher must re-confirm before it can be published again.

Revision ID: 0019_m0_web_review_contracts
Revises: 0018_m0_question_library
Create Date: 2026-09-03
"""

from alembic import op
import sqlalchemy as sa


revision = "0019_m0_web_review_contracts"
down_revision = "0018_m0_question_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("eval_questions")}

    # A fresh database already has both columns: migration 0001 creates the
    # whole schema from the ORM metadata. Only a legacy-head database needs
    # the incremental ADD COLUMN path.
    if "criteria_confirmed" not in columns:
        op.add_column(
            "eval_questions",
            sa.Column(
                "criteria_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
        )
    if "ever_published" not in columns:
        op.add_column(
            "eval_questions",
            sa.Column(
                "ever_published", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
        )
    op.execute(
        "UPDATE eval_questions "
        "SET criteria_confirmed = TRUE, ever_published = TRUE "
        "WHERE status = 'published'"
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("eval_questions")}
    if "ever_published" in columns:
        op.drop_column("eval_questions", "ever_published")
    if "criteria_confirmed" in columns:
        op.drop_column("eval_questions", "criteria_confirmed")
