"""Allow compressed execution artifacts larger than the MySQL BLOB limit.

Revision ID: 0044_execution_artifact_mediumblob
Revises: 0043_test_report_contracts
Create Date: 2026-07-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision: str = "0044_execution_artifact_mediumblob"
down_revision: str | Sequence[str] | None = "0043_test_report_contracts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "execution_payload_artifacts",
        "content",
        existing_type=sa.LargeBinary(),
        type_=mysql.MEDIUMBLOB(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "execution_payload_artifacts",
        "content",
        existing_type=mysql.MEDIUMBLOB(),
        type_=sa.LargeBinary(),
        existing_nullable=True,
    )
