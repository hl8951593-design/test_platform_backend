"""add performance indexes

Revision ID: 0006_add_performance_indexes
Revises: 0005_test_case_body_type
Create Date: 2026-06-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_add_performance_indexes"
down_revision: str | Sequence[str] | None = "0005_test_case_body_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_projects_deleted_id", "projects", ["is_deleted", "id"], unique=False)
    op.create_index(
        "ix_project_members_user_active_project",
        "project_members",
        ["user_id", "is_active", "project_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_environments_project_deleted_default_id",
        "project_environments",
        ["project_id", "is_deleted", "is_default", "id"],
        unique=False,
    )
    op.create_index("ix_test_cases_project_id_id", "test_cases", ["project_id", "id"], unique=False)
    op.create_index(
        "ix_test_case_executions_project_created_at",
        "test_case_executions",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_test_case_executions_case_created_at",
        "test_case_executions",
        ["test_case_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_test_case_executions_case_created_at", table_name="test_case_executions")
    op.drop_index("ix_test_case_executions_project_created_at", table_name="test_case_executions")
    op.drop_index("ix_test_cases_project_id_id", table_name="test_cases")
    op.drop_index(
        "ix_project_environments_project_deleted_default_id",
        table_name="project_environments",
    )
    op.drop_index("ix_project_members_user_active_project", table_name="project_members")
    op.drop_index("ix_projects_deleted_id", table_name="projects")
