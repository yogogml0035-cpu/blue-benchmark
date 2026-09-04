"""Credential 1:1 model: persist plaintext and normalize legacy duplicates.

Adds ``token_plaintext`` to ``scene_credentials`` so the administrator can
view the current credential again from the scene page. Legacy rows keep NULL
(the old model never stored plaintext); they remain usable for authentication
but cannot be revealed until they are replaced.

Normalization policy:
- the new model keeps at most one active credential per scene; a legacy scene
  with several active credentials keeps its newest one and revokes the rest
  with reason ``model-migration``.

Revision ID: 0020_credential_one_to_one
Revises: 0019_m0_web_review_contracts
Create Date: 2026-09-04
"""

from alembic import op
import sqlalchemy as sa


revision = "0020_credential_one_to_one"
down_revision = "0019_m0_web_review_contracts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "scene_credentials" not in set(inspector.get_table_names()):
        return

    # A fresh database already has the column: migration 0001 creates the whole
    # schema from the ORM metadata. Only a legacy-head database needs the
    # incremental ADD COLUMN path.
    columns = {item["name"] for item in inspector.get_columns("scene_credentials")}
    if "token_plaintext" not in columns:
        op.add_column(
            "scene_credentials",
            sa.Column("token_plaintext", sa.Text(), nullable=True),
        )

    # 1:1 normalization: keep the newest active credential per scene, revoke
    # the rest. Small data volume, so per-row UPDATEs are fine on both SQLite
    # and Postgres.
    credentials = sa.table(
        "scene_credentials",
        sa.column("id", sa.String),
        sa.column("scene_id", sa.String),
        sa.column("created_at", sa.DateTime),
        sa.column("revoked_at", sa.DateTime),
        sa.column("revoked_reason", sa.String),
    )
    active = bind.execute(
        sa.select(credentials.c.id, credentials.c.scene_id)
        .where(credentials.c.revoked_at.is_(None))
        .order_by(credentials.c.scene_id, credentials.c.created_at)
    ).fetchall()
    newest_by_scene: dict[str, str] = {}
    for row in active:
        newest_by_scene[row.scene_id] = row.id  # ascending order: last wins
    for row in active:
        if row.id != newest_by_scene[row.scene_id]:
            bind.execute(
                credentials.update()
                .where(credentials.c.id == row.id)
                .values(revoked_at=sa.func.now(), revoked_reason="model-migration")
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "scene_credentials" not in set(inspector.get_table_names()):
        return
    columns = {item["name"] for item in inspector.get_columns("scene_credentials")}
    if "token_plaintext" in columns:
        # batch_alter_table keeps this reversible on SQLite too.
        with op.batch_alter_table("scene_credentials") as batch_op:
            batch_op.drop_column("token_plaintext")
