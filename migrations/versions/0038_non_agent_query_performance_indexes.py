"""Add non-Agent query performance indexes.

Revision ID: 0038_non_agent_query_performance_indexes
Revises: 0037_browser_capture_analysis_audit_fields
Create Date: 2026-07-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "0038_non_agent_query_performance_indexes"
down_revision: str | Sequence[str] | None = "0037_browser_capture_analysis_audit_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_test_scenario_runs_project_started_id",
        "test_scenario_runs",
        ["project_id", "started_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_browser_capture_entries_capture_id_order",
        "browser_capture_entries",
        ["capture_id", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_browser_capture_entries_capture_id_order",
        table_name="browser_capture_entries",
    )
    op.drop_index(
        "ix_test_scenario_runs_project_started_id",
        table_name="test_scenario_runs",
    )
