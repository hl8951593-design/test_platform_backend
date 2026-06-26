"""add agent memory feedback state

Revision ID: 0027_agent_memory_feedback
Revises: 0026_agent_memory_foundation
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0027_agent_memory_feedback"
down_revision: str | Sequence[str] | None = "0026_agent_memory_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_agent_memory_usage_events",
        sa.Column("feedback_state", sa.String(32), nullable=False, server_default="pending"),
    )
    op.add_column("ai_agent_memory_usage_events", sa.Column("feedback_processed_at", sa.DateTime(), nullable=True))
    op.add_column("ai_agent_memory_usage_events", sa.Column("feedback_result_json", sa.JSON(), nullable=True))
    op.create_index(
        "idx_memory_usage_feedback",
        "ai_agent_memory_usage_events",
        ["feedback_state", "outcome", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_memory_usage_feedback", table_name="ai_agent_memory_usage_events")
    op.drop_column("ai_agent_memory_usage_events", "feedback_result_json")
    op.drop_column("ai_agent_memory_usage_events", "feedback_processed_at")
    op.drop_column("ai_agent_memory_usage_events", "feedback_state")
