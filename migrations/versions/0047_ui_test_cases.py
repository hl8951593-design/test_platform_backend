"""Add versioned TestAuto Desktop UI test cases.

Revision ID: 0047_ui_test_cases
Revises: 0046_desktop_devices
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0047_ui_test_cases"
down_revision: str | Sequence[str] | None = "0046_desktop_devices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ui_test_cases",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("default_environment_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("current_version_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["default_environment_id"],
            ["project_environments.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ui_test_cases_public_id", "ui_test_cases", ["public_id"], unique=True)
    op.create_index("ix_ui_test_cases_project_id", "ui_test_cases", ["project_id"])
    op.create_index(
        "ix_ui_test_cases_default_environment_id",
        "ui_test_cases",
        ["default_environment_id"],
    )
    op.create_index(
        "ix_ui_test_cases_current_version_id",
        "ui_test_cases",
        ["current_version_id"],
    )
    op.create_index(
        "ix_ui_test_cases_project_deleted_updated",
        "ui_test_cases",
        ["project_id", "is_deleted", "updated_at", "id"],
    )
    op.create_index(
        "ix_ui_test_cases_project_status_updated",
        "ui_test_cases",
        ["project_id", "status", "updated_at", "id"],
    )

    op.create_table(
        "ui_test_case_versions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ui_test_case_id", sa.BigInteger(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "schema_version",
            sa.String(length=32),
            nullable=False,
            server_default="ui-case-v1",
        ),
        sa.Column("dsl_json", sa.JSON(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("required_secret_refs_json", sa.JSON(), nullable=False),
        sa.Column("based_on_version_id", sa.BigInteger(), nullable=True),
        sa.Column("change_summary", sa.String(length=512), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["based_on_version_id"],
            ["ui_test_case_versions.id"],
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["ui_test_case_id"],
            ["ui_test_cases.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ui_test_case_id",
            "version_number",
            name="uq_ui_test_case_versions_case_version",
        ),
    )
    op.create_index(
        "ix_ui_test_case_versions_ui_test_case_id",
        "ui_test_case_versions",
        ["ui_test_case_id"],
    )
    op.create_index(
        "ix_ui_test_case_versions_based_on_version_id",
        "ui_test_case_versions",
        ["based_on_version_id"],
    )
    op.create_index(
        "ix_ui_test_case_versions_case_created",
        "ui_test_case_versions",
        ["ui_test_case_id", "created_at", "id"],
    )
    op.create_foreign_key(
        "fk_ui_test_cases_current_version_id",
        "ui_test_cases",
        "ui_test_case_versions",
        ["current_version_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_ui_test_cases_current_version_id",
        "ui_test_cases",
        type_="foreignkey",
    )
    op.drop_table("ui_test_case_versions")
    op.drop_table("ui_test_cases")
