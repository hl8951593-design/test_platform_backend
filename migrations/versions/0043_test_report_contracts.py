"""Add one-time test report export credentials.

Revision ID: 0043_test_report_contracts
Revises: 0042_dashboard_workbench_contracts
Create Date: 2026-07-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0043_test_report_contracts"
down_revision: str | Sequence[str] | None = "0042_dashboard_workbench_contracts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "test_report_exports",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False, server_default="html"),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_test_report_exports_project_created",
        "test_report_exports",
        ["project_id", "created_at", "id"],
    )
    op.create_index(
        "ix_test_report_exports_expires",
        "test_report_exports",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_table("test_report_exports")
