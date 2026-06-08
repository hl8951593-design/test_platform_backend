"""add test case body type

Revision ID: 0005_test_case_body_type
Revises: 0004_test_case_tables
Create Date: 2026-06-02
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0005_test_case_body_type"
down_revision: str | Sequence[str] | None = "0004_test_case_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "test_cases",
        sa.Column("body_type", sa.String(length=32), nullable=False, server_default="json", comment="请求体格式"),
    )


def downgrade() -> None:
    op.drop_column("test_cases", "body_type")
