"""Authoring question agents.

Revision ID: 0007_authoring_question_agents
Revises: 0006_authoring_conversations

Superseded by the destructive M0 reset (0018_m0_question_library). The legacy
business schema this step built no longer exists in code or contract; the step
is kept as a revision marker only so databases stamped at intermediate heads
still converge through ``alembic upgrade head``.
"""

from typing import Sequence, Union

revision: str = "0007_authoring_question_agents"
down_revision: Union[str, None] = "0006_authoring_conversations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
