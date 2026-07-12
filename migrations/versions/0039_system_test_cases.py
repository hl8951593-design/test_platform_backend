"""Add system test cases.

Revision ID: 0039_system_test_cases
Revises: 0038_non_agent_query_performance_indexes
Create Date: 2026-07-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0039_system_test_cases"
down_revision: str | Sequence[str] | None = "0038_non_agent_query_performance_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "system_test_cases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("case_code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("business_module", sa.String(length=128), nullable=False),
        sa.Column("test_objective", sa.Text(), nullable=False),
        sa.Column("preconditions", sa.Text(), nullable=True),
        sa.Column("test_scenario", sa.Text(), nullable=True),
        sa.Column("system_behavior", sa.Text(), nullable=True),
        sa.Column("expected_result", sa.Text(), nullable=True),
        sa.Column("data_requirements", sa.Text(), nullable=True),
        sa.Column("risk_points", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("ai_generated", sa.Boolean(), nullable=False),
        sa.Column("ai_confidence", sa.Float(), nullable=True),
        sa.Column("owner", sa.String(length=128), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "case_code", name="uq_system_test_cases_project_code"),
    )
    op.create_index(op.f("ix_system_test_cases_id"), "system_test_cases", ["id"], unique=False)
    op.create_index(op.f("ix_system_test_cases_project_id"), "system_test_cases", ["project_id"], unique=False)
    op.create_index(
        "ix_system_test_cases_project_module",
        "system_test_cases",
        ["project_id", "business_module"],
        unique=False,
    )
    op.create_index(
        "ix_system_test_cases_project_status_priority",
        "system_test_cases",
        ["project_id", "status", "priority"],
        unique=False,
    )
    op.create_index(
        "ix_system_test_cases_project_updated_id",
        "system_test_cases",
        ["project_id", "updated_at", "id"],
        unique=False,
    )

    op.create_table(
        "system_case_api_relations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("system_case_id", sa.Integer(), nullable=False),
        sa.Column("api_case_id", sa.Integer(), nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["api_case_id"], ["test_cases.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["system_case_id"], ["system_test_cases.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("system_case_id", "api_case_id", name="uq_system_case_api_relations_case_api"),
    )
    op.create_index(op.f("ix_system_case_api_relations_api_case_id"), "system_case_api_relations", ["api_case_id"], unique=False)
    op.create_index(op.f("ix_system_case_api_relations_id"), "system_case_api_relations", ["id"], unique=False)
    op.create_index(op.f("ix_system_case_api_relations_project_id"), "system_case_api_relations", ["project_id"], unique=False)
    op.create_index(op.f("ix_system_case_api_relations_system_case_id"), "system_case_api_relations", ["system_case_id"], unique=False)
    op.create_index(
        "ix_system_case_api_relations_project_api",
        "system_case_api_relations",
        ["project_id", "api_case_id"],
        unique=False,
    )
    op.create_index(
        "ix_system_case_api_relations_project_case_order",
        "system_case_api_relations",
        ["project_id", "system_case_id", "sort_order"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("system_case_api_relations")
    op.drop_table("system_test_cases")
