"""Add notification read states.

Revision ID: 0033_notification_read_states
Revises: 0032_execution_history_query_indexes
Create Date: 2026-07-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0033_notification_read_states"
down_revision: str | Sequence[str] | None = "0032_execution_history_query_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_read_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("notification_id", sa.String(length=128), nullable=False),
        sa.Column("read_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "project_id",
            "notification_id",
            name="uq_notification_read_states_user_project_notification",
        ),
    )
    op.create_index(
        "ix_notification_read_states_id",
        "notification_read_states",
        ["id"],
    )
    op.create_index(
        "ix_notification_read_states_project_id",
        "notification_read_states",
        ["project_id"],
    )
    op.create_index(
        "ix_notification_read_states_project_user",
        "notification_read_states",
        ["project_id", "user_id"],
    )
    op.create_index(
        "ix_notification_read_states_user_id",
        "notification_read_states",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_notification_read_states_user_id", table_name="notification_read_states")
    op.drop_index("ix_notification_read_states_project_user", table_name="notification_read_states")
    op.drop_index("ix_notification_read_states_project_id", table_name="notification_read_states")
    op.drop_index("ix_notification_read_states_id", table_name="notification_read_states")
    op.drop_table("notification_read_states")
