"""create test plan tables

Revision ID: 0012_test_plans
Revises: 0011_scenarios
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0012_test_plans"
down_revision: str | Sequence[str] | None = "0011_scenarios"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "test_plans",
        sa.Column("id", sa.Integer(), nullable=False), sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("name", sa.String(128), nullable=False), sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("trigger_type", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("cron_expression", sa.String(128), nullable=True), sa.Column("webhook_event", sa.String(128), nullable=True),
        sa.Column("schedule_timezone", sa.String(64), nullable=False, server_default="Asia/Shanghai"),
        sa.Column("environment_ids", sa.JSON(), nullable=False), sa.Column("targets", sa.JSON(), nullable=False),
        sa.Column("execution_mode", sa.String(32), nullable=False, server_default="serial"),
        sa.Column("failure_policy", sa.String(32), nullable=False, server_default="stop"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("timeout_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("notification_emails", sa.JSON(), nullable=False), sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=False), sa.Column("updated_by_id", sa.Integer(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(), nullable=True), sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]), sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_test_plans_project_name"),
    )
    op.create_index("ix_test_plans_id", "test_plans", ["id"])
    op.create_index("ix_test_plans_project_id", "test_plans", ["project_id"])
    op.create_index("ix_test_plans_project_deleted_updated", "test_plans", ["project_id", "is_deleted", "updated_at"])

    op.create_table(
        "test_plan_scenarios",
        sa.Column("id", sa.Integer(), nullable=False), sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False), sa.Column("scenario_id", sa.Integer(), nullable=False),
        sa.Column("scenario_version_at_bind", sa.Integer(), nullable=False), sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("name_snapshot", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["plan_id"], ["test_plans.id"]), sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["scenario_id"], ["test_scenarios.id"]), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "scenario_id", name="uq_test_plan_scenarios_plan_scenario"),
        sa.UniqueConstraint("plan_id", "sort_order", name="uq_test_plan_scenarios_plan_order"),
    )
    op.create_index("ix_test_plan_scenarios_id", "test_plan_scenarios", ["id"])
    op.create_index("ix_test_plan_scenarios_plan_id", "test_plan_scenarios", ["plan_id"])
    op.create_index("ix_test_plan_scenarios_project_id", "test_plan_scenarios", ["project_id"])
    op.create_index("ix_test_plan_scenarios_scenario_id", "test_plan_scenarios", ["scenario_id"])
    op.create_index("ix_test_plan_scenarios_project_scenario", "test_plan_scenarios", ["project_id", "scenario_id"])

    op.create_table(
        "test_plan_environments",
        sa.Column("id", sa.Integer(), nullable=False), sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False), sa.Column("environment_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["plan_id"], ["test_plans.id"]), sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["environment_id"], ["project_environments.id"]), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "environment_id", name="uq_test_plan_environments_plan_environment"),
    )
    op.create_index("ix_test_plan_environments_id", "test_plan_environments", ["id"])
    op.create_index("ix_test_plan_environments_plan_id", "test_plan_environments", ["plan_id"])
    op.create_index("ix_test_plan_environments_project_id", "test_plan_environments", ["project_id"])
    op.create_index("ix_test_plan_environments_environment_id", "test_plan_environments", ["environment_id"])
    op.create_index("ix_test_plan_environments_project_environment", "test_plan_environments", ["project_id", "environment_id"])

    op.create_table(
        "test_plan_runs",
        sa.Column("id", sa.Integer(), nullable=False), sa.Column("plan_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False), sa.Column("plan_name", sa.String(128), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False), sa.Column("environment_id", sa.Integer(), nullable=True),
        sa.Column("environment_name", sa.String(64), nullable=True), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("trigger", sa.String(32), nullable=False), sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("plan_snapshot", sa.JSON(), nullable=False), sa.Column("target_results", sa.JSON(), nullable=False),
        sa.Column("target_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("operator_id", sa.Integer(), nullable=False), sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True), sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["plan_id"], ["test_plans.id"]), sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["environment_id"], ["project_environments.id"]), sa.ForeignKeyConstraint(["operator_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("project_id", "idempotency_key", name="uq_test_plan_runs_project_idempotency"),
    )
    op.create_index("ix_test_plan_runs_id", "test_plan_runs", ["id"])
    op.create_index("ix_test_plan_runs_plan_id", "test_plan_runs", ["plan_id"])
    op.create_index("ix_test_plan_runs_project_id", "test_plan_runs", ["project_id"])
    op.create_index("ix_test_plan_runs_project_started", "test_plan_runs", ["project_id", "started_at"])


def downgrade() -> None:
    op.drop_table("test_plan_runs")
    op.drop_table("test_plan_environments")
    op.drop_table("test_plan_scenarios")
    op.drop_table("test_plans")
