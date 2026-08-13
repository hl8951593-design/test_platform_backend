"""add report-center deletion tombstones

Revision ID: 0051_test_report_deletions
Revises: 0050_ui_execution_patch_requests
Create Date: 2026-07-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0051_test_report_deletions"
down_revision: str | Sequence[str] | None = "0050_ui_execution_patch_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "test_report_deletions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("deleted_by_id", sa.Integer(), nullable=False),
        sa.Column(
            "deleted_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["deleted_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "source_type",
            "source_id",
            name="uq_test_report_deletions_project_source",
        ),
    )
    op.create_index(
        "ix_test_report_deletions_project_id",
        "test_report_deletions",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_test_report_deletions_project_deleted",
        "test_report_deletions",
        ["project_id", "deleted_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_test_report_deletions_project_deleted",
        table_name="test_report_deletions",
    )
    op.drop_index(
        "ix_test_report_deletions_project_id",
        table_name="test_report_deletions",
    )
    op.drop_table("test_report_deletions")
