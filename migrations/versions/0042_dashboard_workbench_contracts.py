"""Add dashboard workbench read models and async job ledgers.

Revision ID: 0042_dashboard_workbench_contracts
Revises: 0041_execution_diagnostic_read_models
Create Date: 2026-07-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0042_dashboard_workbench_contracts"
down_revision: str | Sequence[str] | None = "0041_execution_diagnostic_read_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dashboard_asset_daily_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=True),
        sa.Column("scope_key", sa.String(length=64), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("http_test_case_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("websocket_test_case_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("system_test_case_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scenario_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scenario_enabled_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("defect_open_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("defect_total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["environment_id"], ["project_environments.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "scope_key", "snapshot_date", name="uq_dashboard_asset_snapshot_scope_date"
        ),
    )
    op.create_index(
        "ix_dashboard_asset_snapshot_project_scope_date",
        "dashboard_asset_daily_snapshots",
        ["project_id", "scope_key", "snapshot_date"],
    )
    op.create_index(
        "ix_dashboard_asset_daily_snapshots_project_id",
        "dashboard_asset_daily_snapshots",
        ["project_id"],
    )
    op.create_index(
        "ix_dashboard_asset_daily_snapshots_environment_id",
        "dashboard_asset_daily_snapshots",
        ["environment_id"],
    )

    op.create_table(
        "dashboard_asset_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=True),
        sa.Column("asset_type", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["environment_id"], ["project_environments.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dashboard_asset_events_project_id", "dashboard_asset_events", ["project_id"])
    op.create_index("ix_dashboard_asset_events_environment_id", "dashboard_asset_events", ["environment_id"])
    op.create_index(
        "ix_dashboard_asset_events_project_occurred",
        "dashboard_asset_events",
        ["project_id", "occurred_at", "id"],
    )
    op.create_index(
        "ix_dashboard_asset_events_project_type_event_occurred",
        "dashboard_asset_events",
        ["project_id", "asset_type", "event_type", "occurred_at"],
    )

    op.create_table(
        "dashboard_ai_analysis_jobs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("range_value", sa.String(length=16), nullable=False),
        sa.Column("analysis_type", sa.String(length=32), nullable=False),
        sa.Column("focus", sa.JSON(), nullable=False),
        sa.Column("user_prompt", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("recommendations", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["environment_id"], ["project_environments.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dashboard_ai_jobs_project_created",
        "dashboard_ai_analysis_jobs",
        ["project_id", "created_at", "id"],
    )
    op.create_index(
        "ix_dashboard_ai_jobs_project_status_updated",
        "dashboard_ai_analysis_jobs",
        ["project_id", "status", "updated_at"],
    )
    op.create_index("ix_dashboard_ai_analysis_jobs_project_id", "dashboard_ai_analysis_jobs", ["project_id"])
    op.create_index(
        "ix_dashboard_ai_analysis_jobs_environment_id", "dashboard_ai_analysis_jobs", ["environment_id"]
    )

    op.create_table(
        "dashboard_regression_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("run_type", sa.String(length=32), nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("strategy", sa.String(length=32), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("request_snapshot", sa.JSON(), nullable=False),
        sa.Column("target_snapshot", sa.JSON(), nullable=False),
        sa.Column("child_executions", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("target_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["environment_id"], ["project_environments.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dashboard_regression_runs_project_created",
        "dashboard_regression_runs",
        ["project_id", "created_at", "id"],
    )
    op.create_index(
        "ix_dashboard_regression_runs_project_status_updated",
        "dashboard_regression_runs",
        ["project_id", "status", "updated_at"],
    )
    op.create_index(
        "ix_dashboard_regression_runs_request_hash",
        "dashboard_regression_runs",
        ["request_hash"],
    )
    op.create_index("ix_dashboard_regression_runs_project_id", "dashboard_regression_runs", ["project_id"])
    op.create_index(
        "ix_dashboard_regression_runs_environment_id", "dashboard_regression_runs", ["environment_id"]
    )


def downgrade() -> None:
    op.drop_table("dashboard_regression_runs")
    op.drop_table("dashboard_ai_analysis_jobs")
    op.drop_table("dashboard_asset_events")
    op.drop_table("dashboard_asset_daily_snapshots")
