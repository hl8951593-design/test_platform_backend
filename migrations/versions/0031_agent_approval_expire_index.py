"""Add Agent approval expire project index.

Revision ID: 0031_agent_approval_expire_index
Revises: 0030_agent_observability_indexes
Create Date: 2026-07-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "0031_agent_approval_expire_index"
down_revision: str | Sequence[str] | None = "0030_agent_observability_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "idx_agent_approvals_project_expires",
        "ai_agent_approvals",
        ["project_id", "approval_status", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_agent_approvals_project_expires", table_name="ai_agent_approvals")
