"""add agent memory staleness and validation events

Revision ID: 0028_agent_memory_staleness_events
Revises: 0027_agent_memory_feedback
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0028_agent_memory_staleness_events"
down_revision: str | Sequence[str] | None = "0027_agent_memory_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_agent_memory_validation_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("memory_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=True),
        sa.Column("tool_call_id", sa.String(64), nullable=True),
        sa.Column("usage_event_id", sa.Integer(), nullable=True),
        sa.Column("validation_source", sa.String(64), nullable=False),
        sa.Column("evidence_ref_json", sa.JSON(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("previous_confidence", sa.Float(), nullable=False),
        sa.Column("new_confidence", sa.Float(), nullable=False),
        sa.Column("previous_stale_score", sa.Float(), nullable=False),
        sa.Column("new_stale_score", sa.Float(), nullable=False),
        sa.Column("previous_status", sa.String(32), nullable=False),
        sa.Column("new_status", sa.String(32), nullable=False),
        sa.Column("validation_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["memory_id"], ["ai_project_memories.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["usage_event_id"], ["ai_agent_memory_usage_events.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_agent_memory_validation_events_id", "ai_agent_memory_validation_events", ["id"])
    op.create_index(
        "idx_memory_validation_project",
        "ai_agent_memory_validation_events",
        ["project_id", "created_at"],
    )
    op.create_index(
        "idx_memory_validation_memory",
        "ai_agent_memory_validation_events",
        ["memory_id", "created_at"],
    )
    op.create_index(
        "idx_memory_validation_source",
        "ai_agent_memory_validation_events",
        ["validation_source", "created_at"],
    )
    op.create_table(
        "ai_agent_memory_staleness_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("memory_id", sa.Integer(), nullable=False),
        sa.Column("evidence_ref_type", sa.String(64), nullable=False),
        sa.Column("evidence_ref_id", sa.String(128), nullable=False),
        sa.Column("stale_reason", sa.String(128), nullable=False),
        sa.Column("previous_stale_score", sa.Float(), nullable=False),
        sa.Column("new_stale_score", sa.Float(), nullable=False),
        sa.Column("previous_status", sa.String(32), nullable=False),
        sa.Column("new_status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["memory_id"], ["ai_project_memories.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_agent_memory_staleness_events_id", "ai_agent_memory_staleness_events", ["id"])
    op.create_index(
        "idx_memory_staleness_project",
        "ai_agent_memory_staleness_events",
        ["project_id", "created_at"],
    )
    op.create_index(
        "idx_memory_staleness_memory",
        "ai_agent_memory_staleness_events",
        ["memory_id", "created_at"],
    )
    op.create_index(
        "idx_memory_staleness_ref",
        "ai_agent_memory_staleness_events",
        ["evidence_ref_type", "evidence_ref_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_memory_staleness_ref", table_name="ai_agent_memory_staleness_events")
    op.drop_index("idx_memory_staleness_memory", table_name="ai_agent_memory_staleness_events")
    op.drop_index("idx_memory_staleness_project", table_name="ai_agent_memory_staleness_events")
    op.drop_index("ix_ai_agent_memory_staleness_events_id", table_name="ai_agent_memory_staleness_events")
    op.drop_table("ai_agent_memory_staleness_events")
    op.drop_index("idx_memory_validation_source", table_name="ai_agent_memory_validation_events")
    op.drop_index("idx_memory_validation_memory", table_name="ai_agent_memory_validation_events")
    op.drop_index("idx_memory_validation_project", table_name="ai_agent_memory_validation_events")
    op.drop_index("ix_ai_agent_memory_validation_events_id", table_name="ai_agent_memory_validation_events")
    op.drop_table("ai_agent_memory_validation_events")
