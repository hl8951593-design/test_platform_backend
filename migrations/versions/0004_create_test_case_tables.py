"""create test case tables

Revision ID: 0004_test_case_tables
Revises: 0003_project_environments
Create Date: 2026-06-02
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0004_test_case_tables"
down_revision: str | Sequence[str] | None = "0003_project_environments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_environment_variables",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False, comment="变量名"),
        sa.Column("value", sa.Text(), nullable=False, comment="变量值"),
        sa.Column("is_secret", sa.Boolean(), nullable=False, server_default=sa.false(), comment="是否敏感"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["environment_id"], ["project_environments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("environment_id", "name", name="uq_project_environment_variables_name"),
    )
    op.create_index("ix_project_environment_variables_id", "project_environment_variables", ["id"], unique=False)
    op.create_index(
        "ix_project_environment_variables_environment_id",
        "project_environment_variables",
        ["environment_id"],
        unique=False,
    )

    op.create_table(
        "test_cases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False, comment="测试用例名称"),
        sa.Column("description", sa.Text(), nullable=True, comment="测试用例描述"),
        sa.Column("method", sa.String(length=16), nullable=False, comment="请求方法"),
        sa.Column("path", sa.String(length=512), nullable=False, comment="请求路径或完整 URL"),
        sa.Column("headers", sa.JSON(), nullable=True, comment="请求头"),
        sa.Column("query_params", sa.JSON(), nullable=True, comment="Query 参数"),
        sa.Column("body", sa.JSON(), nullable=True, comment="请求体"),
        sa.Column("assertions", sa.JSON(), nullable=True, comment="断言配置"),
        sa.Column("extractors", sa.JSON(), nullable=True, comment="变量提取配置"),
        sa.Column("created_by_id", sa.Integer(), nullable=False, comment="创建人"),
        sa.Column("last_executed_at", sa.DateTime(), nullable=True, comment="最近执行时间"),
        sa.Column("last_execution_status", sa.String(length=32), nullable=True, comment="最近执行状态"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["environment_id"], ["project_environments.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_test_cases_id", "test_cases", ["id"], unique=False)
    op.create_index("ix_test_cases_project_id", "test_cases", ["project_id"], unique=False)

    op.create_table(
        "test_case_executions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("test_case_id", sa.Integer(), nullable=True),
        sa.Column("environment_id", sa.Integer(), nullable=True),
        sa.Column("executed_by_id", sa.Integer(), nullable=False, comment="执行人"),
        sa.Column("status", sa.String(length=32), nullable=False, comment="执行状态"),
        sa.Column("request_snapshot", sa.JSON(), nullable=False, comment="请求快照"),
        sa.Column("response_snapshot", sa.JSON(), nullable=True, comment="响应快照"),
        sa.Column("assertion_results", sa.JSON(), nullable=True, comment="断言结果"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="错误信息"),
        sa.Column("duration_ms", sa.Integer(), nullable=True, comment="耗时毫秒"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["environment_id"], ["project_environments.id"]),
        sa.ForeignKeyConstraint(["executed_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["test_case_id"], ["test_cases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_test_case_executions_id", "test_case_executions", ["id"], unique=False)
    op.create_index("ix_test_case_executions_project_id", "test_case_executions", ["project_id"], unique=False)
    op.create_index("ix_test_case_executions_test_case_id", "test_case_executions", ["test_case_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_test_case_executions_test_case_id", table_name="test_case_executions")
    op.drop_index("ix_test_case_executions_project_id", table_name="test_case_executions")
    op.drop_index("ix_test_case_executions_id", table_name="test_case_executions")
    op.drop_table("test_case_executions")

    op.drop_index("ix_test_cases_project_id", table_name="test_cases")
    op.drop_index("ix_test_cases_id", table_name="test_cases")
    op.drop_table("test_cases")

    op.drop_index("ix_project_environment_variables_environment_id", table_name="project_environment_variables")
    op.drop_index("ix_project_environment_variables_id", table_name="project_environment_variables")
    op.drop_table("project_environment_variables")
