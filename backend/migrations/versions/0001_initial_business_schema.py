"""Create the initial business schema.

The first release has no production data. Keeping this migration declarative
through the shared metadata makes the schema used by the test helper and the
deployment migration identical; later revisions must use explicit Alembic
operations instead of mutating this revision.
"""

from typing import Sequence, Union

from alembic import op

from app.lib.database.models import Base


revision: str = "0001_initial_business_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
