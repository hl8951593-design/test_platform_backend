"""create independent websocket test case tables

Revision ID: 0009_websocket_test_cases
Revises: 0008_test_case_environments
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0009_websocket_test_cases"
down_revision: str | Sequence[str] | None = "0008_test_case_environments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "websocket_test_cases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("path", sa.String(512), nullable=False),
        sa.Column("headers", sa.JSON(), nullable=True),
        sa.Column("subprotocols", sa.JSON(), nullable=True),
        sa.Column("messages", sa.JSON(), nullable=True),
        sa.Column("receive_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("connect_timeout_ms", sa.Integer(), nullable=False, server_default="10000"),
        sa.Column("receive_timeout_ms", sa.Integer(), nullable=False, server_default="10000"),
        sa.Column("assertions", sa.JSON(), nullable=True),
        sa.Column("extractors", sa.JSON(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("last_executed_at", sa.DateTime(), nullable=True),
        sa.Column("last_execution_status", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["environment_id"], ["project_environments.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_websocket_test_cases_id", "websocket_test_cases", ["id"])
    op.create_index("ix_websocket_test_cases_project_id", "websocket_test_cases", ["project_id"])
    op.create_index("ix_websocket_test_cases_project_id_id", "websocket_test_cases", ["project_id", "id"])
    op.create_table(
        "websocket_test_case_environments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("websocket_test_case_id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["websocket_test_case_id"], ["websocket_test_cases.id"]),
        sa.ForeignKeyConstraint(["environment_id"], ["project_environments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("websocket_test_case_id", "environment_id", name="uq_websocket_test_case_environments"),
    )
    for column in ("id", "project_id", "websocket_test_case_id", "environment_id"):
        op.create_index(f"ix_websocket_test_case_environments_{column}", "websocket_test_case_environments", [column])
    op.create_index("ix_websocket_case_env_project_environment", "websocket_test_case_environments", ["project_id", "environment_id", "websocket_test_case_id"])
    op.create_table(
        "websocket_test_case_executions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("websocket_test_case_id", sa.Integer(), nullable=True),
        sa.Column("environment_id", sa.Integer(), nullable=True),
        sa.Column("executed_by_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("session_snapshot", sa.JSON(), nullable=False),
        sa.Column("response_snapshot", sa.JSON(), nullable=True),
        sa.Column("assertion_results", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["websocket_test_case_id"], ["websocket_test_cases.id"]),
        sa.ForeignKeyConstraint(["environment_id"], ["project_environments.id"]),
        sa.ForeignKeyConstraint(["executed_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("id", "project_id", "websocket_test_case_id"):
        op.create_index(f"ix_websocket_test_case_executions_{column}", "websocket_test_case_executions", [column])
    op.create_index("ix_websocket_executions_project_created_at", "websocket_test_case_executions", ["project_id", "created_at"])
    op.create_index("ix_websocket_executions_case_created_at", "websocket_test_case_executions", ["websocket_test_case_id", "created_at"])


def downgrade() -> None:
    op.drop_table("websocket_test_case_executions")
    op.drop_table("websocket_test_case_environments")
    op.drop_table("websocket_test_cases")
