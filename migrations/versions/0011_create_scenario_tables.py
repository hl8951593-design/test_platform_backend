"""create scenario tables

Revision ID: 0011_scenarios
Revises: 0010_visual_flows
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0011_scenarios"
down_revision: str | Sequence[str] | None = "0010_visual_flows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "test_scenarios",
        sa.Column("id", sa.Integer(), nullable=False), sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=False), sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("name", sa.String(128), nullable=False), sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False), sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), nullable=False), sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]), sa.ForeignKeyConstraint(["environment_id"], ["project_environments.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]), sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("project_id", "name", name="uq_test_scenarios_project_name"),
    )
    op.create_index("ix_test_scenarios_id", "test_scenarios", ["id"])
    op.create_index("ix_test_scenarios_project_id", "test_scenarios", ["project_id"])
    op.create_index("ix_test_scenarios_project_deleted_updated", "test_scenarios", ["project_id", "is_deleted", "updated_at"])

    op.create_table(
        "test_scenario_versions",
        sa.Column("id", sa.Integer(), nullable=False), sa.Column("scenario_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["scenario_id"], ["test_scenarios.id"]), sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("scenario_id", "version", name="uq_test_scenario_versions_scenario_version"),
    )
    op.create_index("ix_test_scenario_versions_id", "test_scenario_versions", ["id"])
    op.create_index("ix_test_scenario_versions_scenario_id", "test_scenario_versions", ["scenario_id"])

    op.create_table(
        "test_scenario_runs",
        sa.Column("id", sa.Integer(), nullable=False), sa.Column("scenario_id", sa.Integer(), nullable=True),
        sa.Column("scenario_version_id", sa.Integer(), nullable=True), sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=False), sa.Column("dataset_id", sa.String(128), nullable=True),
        sa.Column("dataset_name", sa.String(128), nullable=True), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("trigger_type", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("idempotency_key", sa.String(128), nullable=True), sa.Column("scenario_snapshot", sa.JSON(), nullable=False),
        sa.Column("variables_snapshot", sa.JSON(), nullable=False), sa.Column("step_results", sa.JSON(), nullable=False),
        sa.Column("triggered_by_id", sa.Integer(), nullable=False), sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True), sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["scenario_id"], ["test_scenarios.id"]), sa.ForeignKeyConstraint(["scenario_version_id"], ["test_scenario_versions.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]), sa.ForeignKeyConstraint(["environment_id"], ["project_environments.id"]),
        sa.ForeignKeyConstraint(["triggered_by_id"], ["users.id"]), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_test_scenario_runs_project_idempotency"),
    )
    op.create_index("ix_test_scenario_runs_id", "test_scenario_runs", ["id"])
    op.create_index("ix_test_scenario_runs_scenario_id", "test_scenario_runs", ["scenario_id"])
    op.create_index("ix_test_scenario_runs_project_id", "test_scenario_runs", ["project_id"])
    op.create_index("ix_test_scenario_runs_project_scenario_started", "test_scenario_runs", ["project_id", "scenario_id", "started_at"])


def downgrade() -> None:
    op.drop_table("test_scenario_runs")
    op.drop_table("test_scenario_versions")
    op.drop_table("test_scenarios")
