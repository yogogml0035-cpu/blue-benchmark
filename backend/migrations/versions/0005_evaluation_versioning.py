"""Add working-set lineage, impact reviews and immutable evaluation versions."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0005_evaluation_versioning"
down_revision: Union[str, None] = "0004_cocreation_contracts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "working_set_drafts" not in tables:
        op.create_table(
            "working_set_drafts",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("workspace_id", sa.String(length=36), nullable=False),
            sa.Column("base_version_id", sa.String(length=36), nullable=True),
            sa.Column("active_key", sa.String(length=36), nullable=True),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("contract_revision_id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("freeze_intent_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("discarded_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("active_key", name="uq_working_set_draft_active_key"),
        )
        op.create_index("ix_working_set_draft_workspace_id", "working_set_drafts", ["workspace_id"])
        op.create_index("ix_working_set_draft_base_version_id", "working_set_drafts", ["base_version_id"])
        op.create_index("ix_working_set_draft_status", "working_set_drafts", ["status"])
        op.create_index("ix_working_set_draft_workspace_status", "working_set_drafts", ["workspace_id", "status"])

    tables = _tables()
    if "working_set_members" not in tables:
        op.create_table(
            "working_set_members",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("draft_id", sa.String(length=36), nullable=False),
            sa.Column("task_package_id", sa.String(length=36), nullable=False),
            sa.Column("task_package_revision", sa.Integer(), nullable=False),
            sa.Column("contract_revision_id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("review_status", sa.String(length=32), nullable=False),
            sa.Column("deterministic_conflicts_json", sa.JSON(), nullable=False),
            sa.Column("ai_suggestions_json", sa.JSON(), nullable=False),
            sa.Column("teacher_note", sa.Text(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["draft_id"], ["working_set_drafts.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["task_package_id"], ["task_packages.id"]),
            sa.UniqueConstraint("draft_id", "task_package_id", name="uq_working_set_member_task"),
        )
        op.create_index("ix_working_set_members_draft_id", "working_set_members", ["draft_id"])
        op.create_index("ix_working_set_members_task_package_id", "working_set_members", ["task_package_id"])
        op.create_index("ix_working_set_member_draft_status", "working_set_members", ["draft_id", "status"])

    tables = _tables()
    if "working_set_commands" not in tables:
        op.create_table(
            "working_set_commands",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("draft_id", sa.String(length=36), nullable=False),
            sa.Column("command_id", sa.String(length=255), nullable=False),
            sa.Column("payload_hash", sa.String(length=64), nullable=False),
            sa.Column("result_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["draft_id"], ["working_set_drafts.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("draft_id", "command_id", name="uq_working_set_command"),
        )
        op.create_index("ix_working_set_commands_draft_id", "working_set_commands", ["draft_id"])

    tables = _tables()
    if "contract_impact_reviews" not in tables:
        op.create_table(
            "contract_impact_reviews",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("draft_id", sa.String(length=36), nullable=False),
            sa.Column("task_package_id", sa.String(length=36), nullable=False),
            sa.Column("from_contract_revision_id", sa.String(length=36), nullable=True),
            sa.Column("to_contract_revision_id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("deterministic_conflicts_json", sa.JSON(), nullable=False),
            sa.Column("ai_suggestions_json", sa.JSON(), nullable=False),
            sa.Column("teacher_note", sa.Text(), nullable=True),
            sa.Column("confirmed_by", sa.String(length=36), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["draft_id"], ["working_set_drafts.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["task_package_id"], ["task_packages.id"]),
            sa.ForeignKeyConstraint(["confirmed_by"], ["users.id"]),
            sa.UniqueConstraint("draft_id", "task_package_id", name="uq_contract_impact_review_task"),
        )
        op.create_index("ix_contract_impact_reviews_draft_id", "contract_impact_reviews", ["draft_id"])
        op.create_index("ix_contract_impact_reviews_task_package_id", "contract_impact_reviews", ["task_package_id"])
        op.create_index("ix_contract_impact_reviews_status", "contract_impact_reviews", ["status"])

    tables = _tables()
    if "coverage_snapshots" not in tables:
        op.create_table(
            "coverage_snapshots",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("draft_id", sa.String(length=36), nullable=False),
            sa.Column("draft_revision", sa.Integer(), nullable=False),
            sa.Column("snapshot_json", sa.JSON(), nullable=False),
            sa.Column("risk_confirmed", sa.Boolean(), nullable=False),
            sa.Column("risk_confirmation_note", sa.Text(), nullable=True),
            sa.Column("confirmed_by", sa.String(length=36), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["draft_id"], ["working_set_drafts.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["confirmed_by"], ["users.id"]),
        )
        op.create_index("ix_coverage_snapshots_draft_id", "coverage_snapshots", ["draft_id"])

    if "evaluation_set_versions" not in _tables():
        op.create_table(
            "evaluation_set_versions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("workspace_id", sa.String(length=36), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("draft_id", sa.String(length=36), nullable=False),
            sa.Column("contract_revision_id", sa.String(length=36), nullable=False),
            sa.Column("schema_version", sa.String(length=128), nullable=False),
            sa.Column("freeze_command_id", sa.String(length=255), nullable=False),
            sa.Column("manifest_key", sa.String(length=512), nullable=False),
            sa.Column("runtime_key", sa.String(length=512), nullable=False),
            sa.Column("judge_key", sa.String(length=512), nullable=False),
            sa.Column("provenance_key", sa.String(length=512), nullable=False),
            sa.Column("package_key", sa.String(length=512), nullable=False),
            sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
            sa.Column("runtime_sha256", sa.String(length=64), nullable=False),
            sa.Column("judge_sha256", sa.String(length=64), nullable=False),
            sa.Column("provenance_sha256", sa.String(length=64), nullable=False),
            sa.Column("overall_sha256", sa.String(length=64), nullable=False),
            sa.Column("risk_confirmation_json", sa.JSON(), nullable=False),
            sa.Column("frozen_by", sa.String(length=36), nullable=False),
            sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["draft_id"], ["working_set_drafts.id"]),
            sa.ForeignKeyConstraint(["frozen_by"], ["users.id"]),
            sa.UniqueConstraint("workspace_id", "version_number", name="uq_evaluation_set_version_number"),
            sa.UniqueConstraint("workspace_id", "freeze_command_id", name="uq_evaluation_set_freeze_command"),
            sa.UniqueConstraint("manifest_key"),
            sa.UniqueConstraint("runtime_key"),
            sa.UniqueConstraint("judge_key"),
            sa.UniqueConstraint("provenance_key"),
            sa.UniqueConstraint("package_key"),
            sa.UniqueConstraint("overall_sha256"),
        )
        op.create_index("ix_evaluation_set_versions_workspace_id", "evaluation_set_versions", ["workspace_id"])
        op.create_index("ix_evaluation_set_versions_version_number", "evaluation_set_versions", ["version_number"])
        op.create_index("ix_evaluation_set_versions_draft_id", "evaluation_set_versions", ["draft_id"])
        op.create_index("ix_evaluation_set_version_workspace", "evaluation_set_versions", ["workspace_id", "version_number"])


def downgrade() -> None:
    tables = _tables()
    if "evaluation_set_versions" in tables:
        op.drop_table("evaluation_set_versions")
    if "coverage_snapshots" in tables:
        op.drop_table("coverage_snapshots")
    if "contract_impact_reviews" in tables:
        op.drop_table("contract_impact_reviews")
    if "working_set_commands" in tables:
        op.drop_table("working_set_commands")
    if "working_set_members" in tables:
        op.drop_table("working_set_members")
    if "working_set_drafts" in tables:
        op.drop_table("working_set_drafts")
