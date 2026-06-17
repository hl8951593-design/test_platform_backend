"""add step retry policies and attempt history

Revision ID: 0017_step_retry
Revises: 0016_scenario_records
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0017_step_retry"
down_revision: str | Sequence[str] | None = "0016_scenario_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("test_cases", sa.Column("retry_policy", sa.JSON(), nullable=True))
    op.add_column(
        "test_case_executions",
        sa.Column("attempt_history", sa.JSON(), nullable=True),
    )
    op.add_column(
        "websocket_test_cases",
        sa.Column("retry_policy", sa.JSON(), nullable=True),
    )
    op.add_column(
        "websocket_test_case_executions",
        sa.Column("attempt_history", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("websocket_test_case_executions", "attempt_history")
    op.drop_column("websocket_test_cases", "retry_policy")
    op.drop_column("test_case_executions", "attempt_history")
    op.drop_column("test_cases", "retry_policy")
