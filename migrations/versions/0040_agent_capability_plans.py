"""Add persisted Agent capability plans.

Revision ID: 0040_agent_capability_plans
Revises: 0039_system_test_cases
Create Date: 2026-07-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0040_agent_capability_plans"
down_revision: str | Sequence[str] | None = "0039_system_test_cases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_agent_capability_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("capability_plan_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("parent_capability_plan_id", sa.String(length=64), nullable=True),
        sa.Column("runtime_snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("intent_decision_json", sa.JSON(), nullable=False),
        sa.Column("skill_plan_json", sa.JSON(), nullable=False),
        sa.Column("allowed_tools_json", sa.JSON(), nullable=False),
        sa.Column("tool_aliases_json", sa.JSON(), nullable=False),
        sa.Column("required_facts_json", sa.JSON(), nullable=False),
        sa.Column("reason_codes_json", sa.JSON(), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("capability_plan_id", name="uq_agent_capability_plans_plan_id"),
        sa.UniqueConstraint("run_id", "iteration", "revision", name="uq_agent_capability_plan_run_iter_rev"),
    )
    op.create_index(op.f("ix_ai_agent_capability_plans_id"), "ai_agent_capability_plans", ["id"], unique=False)
    op.create_index(
        "ix_agent_capability_plans_run_iteration_status",
        "ai_agent_capability_plans",
        ["run_id", "iteration", "status"],
        unique=False,
    )
    op.add_column("ai_agent_runs", sa.Column("active_capability_plan_id", sa.String(length=64), nullable=True))
    op.create_index(
        "ix_ai_agent_runs_active_capability_plan_id",
        "ai_agent_runs",
        ["active_capability_plan_id"],
        unique=False,
    )
    op.add_column("ai_agent_tool_calls", sa.Column("capability_plan_id", sa.String(length=64), nullable=True))
    op.create_index(
        "ix_ai_agent_tool_calls_capability_plan_id",
        "ai_agent_tool_calls",
        ["capability_plan_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ai_agent_tool_calls_capability_plan_id", table_name="ai_agent_tool_calls")
    op.drop_column("ai_agent_tool_calls", "capability_plan_id")
    op.drop_index("ix_ai_agent_runs_active_capability_plan_id", table_name="ai_agent_runs")
    op.drop_column("ai_agent_runs", "active_capability_plan_id")
    op.drop_index("ix_agent_capability_plans_run_iteration_status", table_name="ai_agent_capability_plans")
    op.drop_index(op.f("ix_ai_agent_capability_plans_id"), table_name="ai_agent_capability_plans")
    op.drop_table("ai_agent_capability_plans")
