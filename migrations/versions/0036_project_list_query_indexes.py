"""Add project list query indexes.

Revision ID: 0036_project_list_query_indexes
Revises: 0035_defect_dashboard_indexes
Create Date: 2026-07-09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "0036_project_list_query_indexes"
down_revision: str | Sequence[str] | None = "0035_defect_dashboard_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_project_members_project_active_id",
        "project_members",
        ["project_id", "is_active", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_project_members_project_active_id", table_name="project_members")
