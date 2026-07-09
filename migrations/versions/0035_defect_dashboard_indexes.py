"""Add defect dashboard indexes.

Revision ID: 0035_defect_dashboard_indexes
Revises: 0034_test_plan_run_dashboard_indexes
Create Date: 2026-07-09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "0035_defect_dashboard_indexes"
down_revision: str | Sequence[str] | None = "0034_test_plan_run_dashboard_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_defects_project_updated",
        "defects",
        ["project_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_defects_project_updated", table_name="defects")
