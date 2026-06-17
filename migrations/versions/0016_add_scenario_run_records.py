"""add scenario run record identity

Revision ID: 0016_scenario_records
Revises: 0015_scenario_events
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0016_scenario_records"
down_revision: str | Sequence[str] | None = "0015_scenario_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "test_scenario_runs",
        sa.Column("record_id", sa.String(128), nullable=True),
    )
    op.add_column(
        "test_scenario_runs",
        sa.Column("record_name", sa.String(128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("test_scenario_runs", "record_name")
    op.drop_column("test_scenario_runs", "record_id")
