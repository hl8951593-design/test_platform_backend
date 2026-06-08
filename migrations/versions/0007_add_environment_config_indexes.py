"""add environment config indexes

Revision ID: 0007_environment_indexes
Revises: 0006_add_performance_indexes
Create Date: 2026-06-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_environment_indexes"
down_revision: str | Sequence[str] | None = "0006_add_performance_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_test_cases_project_environment_id",
        "test_cases",
        ["project_id", "environment_id", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_test_cases_project_environment_id", table_name="test_cases")
