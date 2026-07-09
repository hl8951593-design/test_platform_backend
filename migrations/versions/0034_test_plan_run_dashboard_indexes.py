"""Add test plan run dashboard indexes.

Revision ID: 0034_test_plan_run_dashboard_indexes
Revises: 0033_notification_read_states
Create Date: 2026-07-09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "0034_test_plan_run_dashboard_indexes"
down_revision: str | Sequence[str] | None = "0033_notification_read_states"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_test_plan_runs_project_env_deleted_started",
        "test_plan_runs",
        ["project_id", "environment_id", "is_deleted", "started_at"],
    )
    op.create_index(
        "ix_test_plan_runs_project_status_deleted_started",
        "test_plan_runs",
        ["project_id", "status", "is_deleted", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_test_plan_runs_project_status_deleted_started", table_name="test_plan_runs")
    op.drop_index("ix_test_plan_runs_project_env_deleted_started", table_name="test_plan_runs")
