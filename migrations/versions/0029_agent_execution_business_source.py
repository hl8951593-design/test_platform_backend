"""Add business execution trigger source fields.

Revision ID: 0029_agent_execution_business_source
Revises: 0028_agent_memory_staleness_events
Create Date: 2026-07-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0029_agent_execution_business_source"
down_revision: str | Sequence[str] | None = "0028_agent_memory_staleness_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


EXECUTION_TABLES = ("test_case_executions", "websocket_test_case_executions")


def upgrade() -> None:
    for table_name in EXECUTION_TABLES:
        op.add_column(
            table_name,
            sa.Column("trigger_source", sa.String(length=32), nullable=False, server_default="manual"),
        )
        op.add_column(table_name, sa.Column("agent_run_id", sa.String(length=64), nullable=True))
        op.add_column(table_name, sa.Column("agent_tool_call_id", sa.String(length=64), nullable=True))
        op.add_column(table_name, sa.Column("trigger_tool_name", sa.String(length=128), nullable=True))
        op.create_index(f"ix_{table_name}_trigger_source", table_name, ["trigger_source"])
        op.create_index(f"ix_{table_name}_agent_run_id", table_name, ["agent_run_id"])


def downgrade() -> None:
    for table_name in reversed(EXECUTION_TABLES):
        op.drop_index(f"ix_{table_name}_agent_run_id", table_name=table_name)
        op.drop_index(f"ix_{table_name}_trigger_source", table_name=table_name)
        op.drop_column(table_name, "trigger_tool_name")
        op.drop_column(table_name, "agent_tool_call_id")
        op.drop_column(table_name, "agent_run_id")
        op.drop_column(table_name, "trigger_source")
