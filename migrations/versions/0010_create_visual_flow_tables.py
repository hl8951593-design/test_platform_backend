"""create visual flow tables

Revision ID: 0010_visual_flows
Revises: 0009_websocket_test_cases
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0010_visual_flows"
down_revision: str | Sequence[str] | None = "0009_websocket_test_cases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "visual_flows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_visual_flows_id", "visual_flows", ["id"])
    op.create_index("ix_visual_flows_project_id", "visual_flows", ["project_id"])
    op.create_index("ix_visual_flows_project_updated", "visual_flows", ["project_id", "updated_at"])

    op.create_table(
        "visual_flow_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("flow_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("definition_hash", sa.String(64), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["flow_id"], ["visual_flows.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("flow_id", "version", name="uq_visual_flow_versions_flow_version"),
    )
    op.create_index("ix_visual_flow_versions_id", "visual_flow_versions", ["id"])
    op.create_index("ix_visual_flow_versions_flow_id", "visual_flow_versions", ["flow_id"])
    op.create_index("ix_visual_flow_versions_flow_version", "visual_flow_versions", ["flow_id", "version"])

    op.create_table(
        "visual_flow_executions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("flow_id", sa.Integer(), nullable=True),
        sa.Column("flow_version_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("trigger_type", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("trigger_user_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("context_snapshot", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["flow_id"], ["visual_flows.id"]),
        sa.ForeignKeyConstraint(["flow_version_id"], ["visual_flow_versions.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["environment_id"], ["project_environments.id"]),
        sa.ForeignKeyConstraint(["trigger_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_visual_flow_executions_idempotency"),
    )
    op.create_index("ix_visual_flow_executions_id", "visual_flow_executions", ["id"])
    op.create_index("ix_visual_flow_executions_flow_id", "visual_flow_executions", ["flow_id"])
    op.create_index("ix_visual_flow_executions_project_id", "visual_flow_executions", ["project_id"])
    op.create_index("ix_visual_flow_executions_project_created", "visual_flow_executions", ["project_id", "created_at"])

    op.create_table(
        "visual_flow_node_executions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("execution_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("request_snapshot", sa.JSON(), nullable=True),
        sa.Column("output_snapshot", sa.JSON(), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["execution_id"], ["visual_flow_executions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id", "node_id", name="uq_visual_flow_node_executions_node"),
    )
    op.create_index("ix_visual_flow_node_executions_id", "visual_flow_node_executions", ["id"])
    op.create_index("ix_visual_flow_node_executions_execution_id", "visual_flow_node_executions", ["execution_id"])
    op.create_index("ix_visual_flow_node_executions_execution", "visual_flow_node_executions", ["execution_id", "id"])


def downgrade() -> None:
    op.drop_table("visual_flow_node_executions")
    op.drop_table("visual_flow_executions")
    op.drop_table("visual_flow_versions")
    op.drop_table("visual_flows")
