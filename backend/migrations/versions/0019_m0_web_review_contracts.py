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
    existing_tables = set(inspector.get_table_names())

    # Session generation tracking: a password change bumps the user's
    # generation and every session must carry the generation it was created
    # under. Existing rows start at 1, matching fresh-database defaults.
    if "users" in existing_tables:
        user_columns = {item["name"] for item in inspector.get_columns("users")}
        if "password_generation" not in user_columns:
            op.add_column(
                "users",
                sa.Column(
                    "password_generation", sa.Integer(), nullable=False, server_default="1"
                ),
            )
    if "sessions" in existing_tables:
        session_columns = {item["name"] for item in inspector.get_columns("sessions")}
        if "password_generation" not in session_columns:
            op.add_column(
                "sessions",
                sa.Column(
                    "password_generation", sa.Integer(), nullable=False, server_default="1"
                ),
            )

    question_columns = {item["name"] for item in inspector.get_columns("eval_questions")}

    # A fresh database already has both columns: migration 0001 creates the
    # whole schema from the ORM metadata. Only a legacy-head database needs
    # the incremental ADD COLUMN path.
    if "criteria_confirmed" not in question_columns:
        op.add_column(
            "eval_questions",
            sa.Column(
                "criteria_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
        )
    if "ever_published" not in question_columns:
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
    existing_tables = set(inspector.get_table_names())
    question_columns = {item["name"] for item in inspector.get_columns("eval_questions")}
    if "ever_published" in question_columns:
        op.drop_column("eval_questions", "ever_published")
    if "criteria_confirmed" in question_columns:
        op.drop_column("eval_questions", "criteria_confirmed")
    if "sessions" in existing_tables:
        session_columns = {item["name"] for item in inspector.get_columns("sessions")}
        if "password_generation" in session_columns:
            op.drop_column("sessions", "password_generation")
    if "users" in existing_tables:
        user_columns = {item["name"] for item in inspector.get_columns("users")}
        if "password_generation" in user_columns:
            op.drop_column("users", "password_generation")
