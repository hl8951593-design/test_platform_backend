"""create project environments table

Revision ID: 0003_project_environments
Revises: 0002_project_permissions
Create Date: 2026-06-02
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0003_project_environments"
down_revision: str | Sequence[str] | None = "0002_project_permissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_environments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False, comment="环境名称"),
        sa.Column("base_url", sa.String(length=512), nullable=False, comment="环境基础地址"),
        sa.Column("description", sa.Text(), nullable=True, comment="环境描述"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false(), comment="是否默认环境"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false(), comment="是否删除"),
        sa.Column("created_by_id", sa.Integer(), nullable=False, comment="创建人"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_project_environments_project_name"),
    )
    op.create_index("ix_project_environments_id", "project_environments", ["id"], unique=False)
    op.create_index("ix_project_environments_project_id", "project_environments", ["project_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_project_environments_project_id", table_name="project_environments")
    op.drop_index("ix_project_environments_id", table_name="project_environments")
    op.drop_table("project_environments")
