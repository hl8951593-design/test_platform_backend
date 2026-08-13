"""Add environment database connections and scenario database action audit.

Revision ID: 0045_database_test_actions
Revises: 0044_execution_artifact_mediumblob
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0045_database_test_actions"
down_revision: str | Sequence[str] | None = "0044_execution_artifact_mediumblob"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_database_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("connection_key", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("database_name", sa.String(length=128), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("password_encrypted", sa.Text(), nullable=True),
        sa.Column("options_json", sa.JSON(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allow_writes", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("connect_timeout_ms", sa.Integer(), nullable=False, server_default="5000"),
        sa.Column("statement_timeout_ms", sa.Integer(), nullable=False, server_default="10000"),
        sa.Column("max_rows", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["environment_id"], ["project_environments.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "environment_id",
            "connection_key",
            name="uq_project_database_connections_environment_key",
        ),
    )
    op.create_index(
        "ix_project_database_connections_project_environment_active",
        "project_database_connections",
        ["project_id", "environment_id", "is_deleted", "is_enabled", "id"],
    )
    op.create_index(
        "ix_project_database_connections_environment_id",
        "project_database_connections",
        ["environment_id"],
    )
    op.create_index(
        "ix_project_database_connections_project_id",
        "project_database_connections",
        ["project_id"],
    )

    op.create_table(
        "database_action_executions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("scenario_run_id", sa.Integer(), nullable=True),
        sa.Column("step_id", sa.String(length=128), nullable=False),
        sa.Column("action_kind", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("statement_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("request_snapshot", sa.JSON(), nullable=True),
        sa.Column("result_snapshot", sa.JSON(), nullable=True),
        sa.Column("assertion_results", sa.JSON(), nullable=True),
        sa.Column("attempt_history", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("triggered_by_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.ForeignKeyConstraint(["connection_id"], ["project_database_connections.id"]),
        sa.ForeignKeyConstraint(["environment_id"], ["project_environments.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["scenario_run_id"], ["test_scenario_runs.id"]),
        sa.ForeignKeyConstraint(["triggered_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_database_action_executions_connection_id",
        "database_action_executions",
        ["connection_id"],
    )
    op.create_index(
        "ix_database_action_executions_environment_id",
        "database_action_executions",
        ["environment_id"],
    )
    op.create_index(
        "ix_database_action_executions_project_id",
        "database_action_executions",
        ["project_id"],
    )
    op.create_index(
        "ix_database_action_executions_scenario_run_id",
        "database_action_executions",
        ["scenario_run_id"],
    )
    op.create_index(
        "ix_database_action_executions_project_created",
        "database_action_executions",
        ["project_id", "created_at", "id"],
    )
    op.create_index(
        "ix_database_action_executions_scenario_step",
        "database_action_executions",
        ["scenario_run_id", "step_id", "id"],
    )


def downgrade() -> None:
    op.drop_table("database_action_executions")
    op.drop_table("project_database_connections")
