"""Make upload commands idempotent within a workspace.

Revision ID: 0003_upload_command_id
Revises: 0002_attempt_uniqueness

Superseded by the destructive M0 reset (0018_m0_question_library). The legacy
business schema this step built no longer exists in code or contract; the step
is kept as a revision marker only so databases stamped at intermediate heads
still converge through ``alembic upgrade head``.
"""

from typing import Sequence, Union

revision: str = "0003_upload_command_id"
down_revision: Union[str, None] = "0002_attempt_uniqueness"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
