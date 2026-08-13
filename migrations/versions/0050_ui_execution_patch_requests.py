"""link platform patch requests to applied runtime patches

Revision ID: 0050_ui_execution_patch_requests
Revises: 0049_ui_execution_artifact_delivery
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0050_ui_execution_patch_requests"
down_revision: str | Sequence[str] | None = "0049_ui_execution_artifact_delivery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ui_runtime_patches",
        sa.Column("request_command_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_ui_runtime_patches_request_command",
        "ui_runtime_patches",
        "ui_execution_commands",
        ["request_command_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_ui_runtime_patches_request_command_id",
        "ui_runtime_patches",
        ["request_command_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_ui_runtime_patches_request_command",
        "ui_runtime_patches",
        ["request_command_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_ui_runtime_patches_request_command",
        "ui_runtime_patches",
        type_="unique",
    )
    op.drop_index(
        "ix_ui_runtime_patches_request_command_id",
        table_name="ui_runtime_patches",
    )
    op.drop_constraint(
        "fk_ui_runtime_patches_request_command",
        "ui_runtime_patches",
        type_="foreignkey",
    )
    op.drop_column("ui_runtime_patches", "request_command_id")
