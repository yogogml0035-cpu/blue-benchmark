"""Prevent duplicate run attempts for one operation.

Revision ID: 0002_attempt_uniqueness
Revises: 0001_initial_business_schema

Superseded by the destructive M0 reset (0018_m0_question_library). The legacy
business schema this step built no longer exists in code or contract; the step
is kept as a revision marker only so databases stamped at intermediate heads
still converge through ``alembic upgrade head``.
"""

from typing import Sequence, Union

revision: str = "0002_attempt_uniqueness"
down_revision: Union[str, None] = "0001_initial_business_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
