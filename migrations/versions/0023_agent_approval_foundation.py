"""add agent approval foundation

Revision ID: 0023_agent_approval_foundation
Revises: 0022_agent_reconcile_foundation
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0023_agent_approval_foundation"
down_revision: str | Sequence[str] | None = "0022_agent_reconcile_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_agent_tool_calls", sa.Column("approval_lineage_id", sa.String(64), nullable=True))
    op.add_column(
        "ai_agent_tool_calls",
        sa.Column("approval_epoch", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("ai_agent_tool_calls", sa.Column("approved_approval_id", sa.String(64), nullable=True))
    op.add_column("ai_agent_tool_calls", sa.Column("approved_by", sa.Integer(), nullable=True))
    op.add_column("ai_agent_tool_calls", sa.Column("approved_at", sa.DateTime(), nullable=True))
    op.create_foreign_key(
        "fk_agent_tool_calls_approved_by_users",
        "ai_agent_tool_calls",
        "users",
        ["approved_by"],
        ["id"],
    )

    op.create_table(
        "ai_agent_approval_lineages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("approval_lineage_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("tool_call_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("current_epoch", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("immutable_input_hash", sa.String(64), nullable=False),
        sa.Column("runtime_snapshot_id", sa.String(64), nullable=False),
        sa.Column("resource_scope_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("approval_lineage_id", name="uq_agent_approval_lineages_lineage_id"),
    )
    op.create_index("ix_ai_agent_approval_lineages_id", "ai_agent_approval_lineages", ["id"])
    op.create_index("idx_agent_approval_lineages_tool_call", "ai_agent_approval_lineages", ["tool_call_id"])
    op.create_index(
        "idx_agent_approval_lineages_run",
        "ai_agent_approval_lineages",
        ["run_id", "status", "created_at"],
    )

    op.create_table(
        "ai_agent_approvals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("approval_id", sa.String(64), nullable=False),
        sa.Column("approval_lineage_id", sa.String(64), nullable=False),
        sa.Column("approval_epoch", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("tool_call_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("approval_status", sa.String(32), nullable=False),
        sa.Column("requested_by", sa.Integer(), nullable=False),
        sa.Column("decided_by", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("runtime_snapshot_id", sa.String(64), nullable=False),
        sa.Column("resource_scope_hash", sa.String(64), nullable=False),
        sa.Column("approval_reason", sa.String(256), nullable=True),
        sa.Column("decision_reason", sa.String(512), nullable=True),
        sa.Column("required_permissions_json", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("approval_id", name="uq_agent_approvals_approval_id"),
        sa.UniqueConstraint("approval_lineage_id", "approval_epoch", name="uq_agent_approvals_lineage_epoch"),
    )
    op.create_index("ix_ai_agent_approvals_id", "ai_agent_approvals", ["id"])
    op.create_index("idx_agent_approvals_tool_status", "ai_agent_approvals", ["tool_call_id", "approval_status"])
    op.create_index("idx_agent_approvals_run_status", "ai_agent_approvals", ["run_id", "approval_status"])
    op.create_index(
        "idx_agent_approvals_lineage_status",
        "ai_agent_approvals",
        ["approval_lineage_id", "approval_status"],
    )
    op.create_index("idx_agent_approvals_expires", "ai_agent_approvals", ["approval_status", "expires_at"])

    op.create_table(
        "ai_agent_approval_mutation_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("approval_lineage_id", sa.String(64), nullable=False),
        sa.Column("approval_id", sa.String(64), nullable=True),
        sa.Column("tool_call_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("mutation_type", sa.String(64), nullable=False),
        sa.Column("from_status", sa.String(32), nullable=True),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(512), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_agent_approval_mutation_logs_id", "ai_agent_approval_mutation_logs", ["id"])
    op.create_index(
        "idx_agent_approval_mutation_logs_lineage",
        "ai_agent_approval_mutation_logs",
        ["approval_lineage_id", "created_at"],
    )
    op.create_index(
        "idx_agent_approval_mutation_logs_tool_call",
        "ai_agent_approval_mutation_logs",
        ["tool_call_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("ai_agent_approval_mutation_logs")
    op.drop_table("ai_agent_approvals")
    op.drop_table("ai_agent_approval_lineages")
    op.drop_constraint("fk_agent_tool_calls_approved_by_users", "ai_agent_tool_calls", type_="foreignkey")
    op.drop_column("ai_agent_tool_calls", "approved_at")
    op.drop_column("ai_agent_tool_calls", "approved_by")
    op.drop_column("ai_agent_tool_calls", "approved_approval_id")
    op.drop_column("ai_agent_tool_calls", "approval_epoch")
    op.drop_column("ai_agent_tool_calls", "approval_lineage_id")
