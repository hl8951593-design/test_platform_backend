"""create test case environments

Revision ID: 0008_test_case_environments
Revises: 0007_environment_indexes
Create Date: 2026-06-04
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0008_test_case_environments"
down_revision: str | Sequence[str] | None = "0007_environment_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "test_case_environments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("test_case_id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["environment_id"], ["project_environments.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["test_case_id"], ["test_cases.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("test_case_id", "environment_id", name="uq_test_case_environments_case_env"),
    )
    op.create_index("ix_test_case_environments_id", "test_case_environments", ["id"], unique=False)
    op.create_index(
        "ix_test_case_environments_project_id",
        "test_case_environments",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_test_case_environments_test_case_id",
        "test_case_environments",
        ["test_case_id"],
        unique=False,
    )
    op.create_index(
        "ix_test_case_environments_environment_id",
        "test_case_environments",
        ["environment_id"],
        unique=False,
    )
    op.create_index(
        "ix_test_case_environments_project_environment",
        "test_case_environments",
        ["project_id", "environment_id", "test_case_id"],
        unique=False,
    )
    op.execute(
        """
        INSERT INTO test_case_environments (project_id, test_case_id, environment_id)
        SELECT project_id, id, environment_id
        FROM test_cases
        WHERE environment_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_test_case_environments_project_environment", table_name="test_case_environments")
    op.drop_index("ix_test_case_environments_environment_id", table_name="test_case_environments")
    op.drop_index("ix_test_case_environments_test_case_id", table_name="test_case_environments")
    op.drop_index("ix_test_case_environments_project_id", table_name="test_case_environments")
    op.drop_index("ix_test_case_environments_id", table_name="test_case_environments")
    op.drop_table("test_case_environments")
