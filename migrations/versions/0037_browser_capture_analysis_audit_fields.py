"""Add browser capture analysis audit fields.

Revision ID: 0037_browser_capture_analysis_audit_fields
Revises: 0036_project_list_query_indexes
Create Date: 2026-07-09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0037_browser_capture_analysis_audit_fields"
down_revision: str | Sequence[str] | None = "0036_project_list_query_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("browser_capture_entries", sa.Column("ai_analysis_model", sa.String(length=128), nullable=True))
    op.add_column("browser_capture_entries", sa.Column("ai_analyzed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("browser_capture_entries", "ai_analyzed_at")
    op.drop_column("browser_capture_entries", "ai_analysis_model")
