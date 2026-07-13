"""Add execution history query indexes.

Revision ID: 0032_execution_history_query_indexes
Revises: 0031_agent_approval_expire_index
Create Date: 2026-07-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "0032_execution_history_query_indexes"
down_revision: str | Sequence[str] | None = "0031_agent_approval_expire_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_test_case_executions_project_status_created",
        "test_case_executions",
        ["project_id", "status", "created_at"],
    )
    op.create_index(
        "ix_test_case_executions_project_env_created",
        "test_case_executions",
        ["project_id", "environment_id", "created_at"],
    )
    op.create_index(
        "ix_test_case_executions_project_user_created",
        "test_case_executions",
        ["project_id", "executed_by_id", "created_at"],
    )
    op.create_index(
        "ix_test_case_executions_agent_tool_call_id",
        "test_case_executions",
        ["agent_tool_call_id"],
    )

    op.create_index(
        "ix_websocket_executions_project_status_created",
        "websocket_test_case_executions",
        ["project_id", "status", "created_at"],
    )
    op.create_index(
        "ix_websocket_executions_project_env_created",
        "websocket_test_case_executions",
        ["project_id", "environment_id", "created_at"],
    )
    op.create_index(
        "ix_websocket_executions_project_user_created",
        "websocket_test_case_executions",
        ["project_id", "executed_by_id", "created_at"],
    )
    op.create_index(
        "ix_websocket_executions_agent_tool_call_id",
        "websocket_test_case_executions",
        ["agent_tool_call_id"],
    )

    op.create_index(
        "ix_test_scenario_runs_project_status_started",
        "test_scenario_runs",
        ["project_id", "status", "started_at"],
    )
    op.create_index(
        "ix_test_scenario_runs_project_env_started",
        "test_scenario_runs",
        ["project_id", "environment_id", "started_at"],
    )
    op.create_index(
        "ix_test_scenario_runs_project_user_started",
        "test_scenario_runs",
        ["project_id", "triggered_by_id", "started_at"],
    )
    op.create_index(
        "ix_test_scenario_runs_project_dataset_record",
        "test_scenario_runs",
        ["project_id", "dataset_id", "record_id"],
    )

    op.create_index(
        "ix_visual_flow_executions_project_status_created",
        "visual_flow_executions",
        ["project_id", "status", "created_at"],
    )
    op.create_index(
        "ix_visual_flow_executions_project_env_created",
        "visual_flow_executions",
        ["project_id", "environment_id", "created_at"],
    )
    op.create_index(
        "ix_visual_flow_executions_project_user_created",
        "visual_flow_executions",
        ["project_id", "trigger_user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_visual_flow_executions_project_user_created", table_name="visual_flow_executions")
    op.drop_index("ix_visual_flow_executions_project_env_created", table_name="visual_flow_executions")
    op.drop_index("ix_visual_flow_executions_project_status_created", table_name="visual_flow_executions")

    op.drop_index("ix_test_scenario_runs_project_dataset_record", table_name="test_scenario_runs")
    op.drop_index("ix_test_scenario_runs_project_user_started", table_name="test_scenario_runs")
    op.drop_index("ix_test_scenario_runs_project_env_started", table_name="test_scenario_runs")
    op.drop_index("ix_test_scenario_runs_project_status_started", table_name="test_scenario_runs")

    op.drop_index("ix_websocket_executions_agent_tool_call_id", table_name="websocket_test_case_executions")
    op.drop_index("ix_websocket_executions_project_user_created", table_name="websocket_test_case_executions")
    op.drop_index("ix_websocket_executions_project_env_created", table_name="websocket_test_case_executions")
    op.drop_index("ix_websocket_executions_project_status_created", table_name="websocket_test_case_executions")

    op.drop_index("ix_test_case_executions_agent_tool_call_id", table_name="test_case_executions")
    op.drop_index("ix_test_case_executions_project_user_created", table_name="test_case_executions")
    op.drop_index("ix_test_case_executions_project_env_created", table_name="test_case_executions")
    op.drop_index("ix_test_case_executions_project_status_created", table_name="test_case_executions")
