"""add scenario realtime execution events

Revision ID: 0015_scenario_events
Revises: 0014_browser_captures
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0015_scenario_events"
down_revision: str | Sequence[str] | None = "0014_browser_captures"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "test_scenario_executions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("scenario_id", sa.Integer(), nullable=True),
        sa.Column("scenario_version_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("triggered_by_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["scenario_id"], ["test_scenarios.id"]),
        sa.ForeignKeyConstraint(["scenario_version_id"], ["test_scenario_versions.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["triggered_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "idempotency_key", name="uq_scenario_executions_project_idempotency"
        ),
    )
    op.create_index(
        "ix_scenario_executions_project_created",
        "test_scenario_executions",
        ["project_id", "created_at"],
    )
    op.create_index("ix_scenario_executions_project_id", "test_scenario_executions", ["project_id"])
    op.create_index("ix_scenario_executions_scenario_id", "test_scenario_executions", ["scenario_id"])

    op.add_column("test_scenario_runs", sa.Column("execution_id", sa.String(36), nullable=True))
    op.add_column("test_scenario_runs", sa.Column("current_step_id", sa.String(128), nullable=True))
    op.add_column("test_scenario_runs", sa.Column("current_step_index", sa.Integer(), nullable=True))
    op.add_column(
        "test_scenario_runs",
        sa.Column("last_event_sequence", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_foreign_key(
        "fk_test_scenario_runs_execution_id",
        "test_scenario_runs",
        "test_scenario_executions",
        ["execution_id"],
        ["id"],
    )
    op.create_index("ix_test_scenario_runs_execution_id", "test_scenario_runs", ["execution_id"])

    op.create_table(
        "test_scenario_run_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["test_scenario_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_scenario_run_events_run_sequence"),
    )
    op.create_index("ix_test_scenario_run_events_id", "test_scenario_run_events", ["id"])
    op.create_index("ix_test_scenario_run_events_run_id", "test_scenario_run_events", ["run_id"])
    op.create_index(
        "ix_scenario_run_events_run_sequence",
        "test_scenario_run_events",
        ["run_id", "sequence"],
    )


def downgrade() -> None:
    op.drop_table("test_scenario_run_events")
    op.drop_index("ix_test_scenario_runs_execution_id", table_name="test_scenario_runs")
    op.drop_constraint(
        "fk_test_scenario_runs_execution_id", "test_scenario_runs", type_="foreignkey"
    )
    op.drop_column("test_scenario_runs", "last_event_sequence")
    op.drop_column("test_scenario_runs", "current_step_index")
    op.drop_column("test_scenario_runs", "current_step_id")
    op.drop_column("test_scenario_runs", "execution_id")
    op.drop_table("test_scenario_executions")
