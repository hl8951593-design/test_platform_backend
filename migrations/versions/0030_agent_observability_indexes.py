"""Add Agent observability query indexes.

Revision ID: 0030_agent_observability_indexes
Revises: 0029_agent_execution_business_source
Create Date: 2026-07-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "0030_agent_observability_indexes"
down_revision: str | Sequence[str] | None = "0029_agent_execution_business_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("idx_agent_events_type_run", "ai_agent_events", ["event_type", "run_id"])
    op.create_index(
        "idx_agent_approval_mutation_logs_run_type",
        "ai_agent_approval_mutation_logs",
        ["run_id", "mutation_type"],
    )
    op.create_index(
        "idx_agent_loop_observations_run_stop",
        "ai_agent_loop_observations",
        ["run_id", "stop_action_reason"],
    )
    op.create_index(
        "idx_agent_loop_observations_run_root",
        "ai_agent_loop_observations",
        ["run_id", "root_cause_primary"],
    )
    op.create_index(
        "idx_memory_contradiction_run_type",
        "ai_agent_memory_contradiction_events",
        ["run_id", "contradiction_type"],
    )


def downgrade() -> None:
    op.drop_index("idx_memory_contradiction_run_type", table_name="ai_agent_memory_contradiction_events")
    op.drop_index("idx_agent_loop_observations_run_root", table_name="ai_agent_loop_observations")
    op.drop_index("idx_agent_loop_observations_run_stop", table_name="ai_agent_loop_observations")
    op.drop_index("idx_agent_approval_mutation_logs_run_type", table_name="ai_agent_approval_mutation_logs")
    op.drop_index("idx_agent_events_type_run", table_name="ai_agent_events")
