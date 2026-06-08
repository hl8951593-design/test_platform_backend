"""create project permission tables

Revision ID: 0002_project_permissions
Revises: 0001_users
Create Date: 2026-06-02
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002_project_permissions"
down_revision: str | Sequence[str] | None = "0001_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false(), comment="是否管理员"),
    )

    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False, comment="项目名称"),
        sa.Column("description", sa.Text(), nullable=True, comment="项目描述"),
        sa.Column("created_by_id", sa.Integer(), nullable=False, comment="项目创建者"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false(), comment="是否删除"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_projects_id", "projects", ["id"], unique=False)
    op.create_index("ix_projects_created_by_id", "projects", ["created_by_id"], unique=False)

    op.create_table(
        "project_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("added_by_id", sa.Integer(), nullable=False, comment="添加人"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true(), comment="是否有效"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["added_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),
    )
    op.create_index("ix_project_members_id", "project_members", ["id"], unique=False)
    op.create_index("ix_project_members_project_id", "project_members", ["project_id"], unique=False)
    op.create_index("ix_project_members_user_id", "project_members", ["user_id"], unique=False)

    op.create_table(
        "project_member_permissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("permission_code", sa.String(length=64), nullable=False, comment="权限编码"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["member_id"], ["project_members.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("member_id", "permission_code", name="uq_project_member_permissions_code"),
    )
    op.create_index("ix_project_member_permissions_id", "project_member_permissions", ["id"], unique=False)
    op.create_index("ix_project_member_permissions_member_id", "project_member_permissions", ["member_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_project_member_permissions_member_id", table_name="project_member_permissions")
    op.drop_index("ix_project_member_permissions_id", table_name="project_member_permissions")
    op.drop_table("project_member_permissions")

    op.drop_index("ix_project_members_user_id", table_name="project_members")
    op.drop_index("ix_project_members_project_id", table_name="project_members")
    op.drop_index("ix_project_members_id", table_name="project_members")
    op.drop_table("project_members")

    op.drop_index("ix_projects_created_by_id", table_name="projects")
    op.drop_index("ix_projects_id", table_name="projects")
    op.drop_table("projects")

    op.drop_column("users", "is_admin")
