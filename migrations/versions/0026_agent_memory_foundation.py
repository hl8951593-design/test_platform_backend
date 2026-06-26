"""add agent memory foundation

Revision ID: 0026_agent_memory_foundation
Revises: 0025_agent_migration_resolution
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0026_agent_memory_foundation"
down_revision: str | Sequence[str] | None = "0025_agent_migration_resolution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_project_memories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("memory_type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("memory_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_ref_json", sa.JSON(), nullable=True),
        sa.Column("authority", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("initial_confidence", sa.Float(), nullable=False),
        sa.Column("confidence_reason_json", sa.JSON(), nullable=True),
        sa.Column("contradiction_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recent_contradiction_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("validation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recent_validation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_contradicted_at", sa.DateTime(), nullable=True),
        sa.Column("last_failure_fingerprint", sa.String(64), nullable=True),
        sa.Column("max_recent_severity", sa.String(32), nullable=True),
        sa.Column("stale_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("stale_reason_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("last_validated_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("evidence_refs_json", sa.JSON(), nullable=True),
        sa.Column("watched_refs_json", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_project_memories_id", "ai_project_memories", ["id"])
    op.create_index(
        "idx_memory_retrieval",
        "ai_project_memories",
        ["project_id", "memory_type", "status", "confidence", "stale_score"],
    )
    op.create_index("idx_memory_source", "ai_project_memories", ["project_id", "source_type", "status"])
    op.create_index("idx_memory_hash", "ai_project_memories", ["project_id", "content_hash"])
    op.create_index("idx_memory_stale", "ai_project_memories", ["project_id", "status", "stale_score", "updated_at"])

    op.create_table(
        "ai_agent_memory_source_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("initial_confidence", sa.Float(), nullable=False),
        sa.Column("authority", sa.String(64), nullable=False),
        sa.Column("default_ttl_days", sa.Integer(), nullable=True),
        sa.Column("requires_source_ref", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("requires_content_hash", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allowed_for_high_risk", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_type", name="uq_agent_memory_source_profiles_source_type"),
    )
    op.create_index("ix_ai_agent_memory_source_profiles_id", "ai_agent_memory_source_profiles", ["id"])

    op.create_table(
        "ai_agent_memory_retrieval_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_name", sa.String(64), nullable=False),
        sa.Column("task_scope", sa.String(64), nullable=False),
        sa.Column("risk_level", sa.String(32), nullable=False),
        sa.Column("min_confidence", sa.Float(), nullable=False),
        sa.Column("max_stale_score", sa.Float(), nullable=False),
        sa.Column("allow_memory_for_high_risk", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("semantic_weight", sa.Float(), nullable=False),
        sa.Column("confidence_weight", sa.Float(), nullable=False),
        sa.Column("recency_weight", sa.Float(), nullable=False),
        sa.Column("authority_weight", sa.Float(), nullable=False),
        sa.Column("validation_weight", sa.Float(), nullable=False),
        sa.Column("stale_weight", sa.Float(), nullable=False),
        sa.Column("contradiction_weight", sa.Float(), nullable=False),
        sa.Column("max_contradiction_penalty", sa.Float(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_name", name="uq_agent_memory_retrieval_profiles_name"),
    )
    op.create_index("ix_ai_agent_memory_retrieval_profiles_id", "ai_agent_memory_retrieval_profiles", ["id"])
    op.create_index(
        "idx_agent_memory_retrieval_profiles_status",
        "ai_agent_memory_retrieval_profiles",
        ["status", "profile_name"],
    )

    op.create_table(
        "ai_agent_memory_usage_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("memory_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=True),
        sa.Column("iteration", sa.Integer(), nullable=True),
        sa.Column("step_index", sa.Integer(), nullable=True),
        sa.Column("tool_call_id", sa.String(64), nullable=True),
        sa.Column("context_build_id", sa.String(64), nullable=True),
        sa.Column("retrieval_profile", sa.String(64), nullable=False),
        sa.Column("retrieval_score", sa.Float(), nullable=False),
        sa.Column("usage_role", sa.String(64), nullable=False),
        sa.Column("active_for_policy", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("caused_tool_input_change", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("outcome", sa.String(64), nullable=True),
        sa.Column("evidence_ref_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["memory_id"], ["ai_project_memories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_agent_memory_usage_events_id", "ai_agent_memory_usage_events", ["id"])
    op.create_index("idx_memory_usage_memory", "ai_agent_memory_usage_events", ["memory_id", "created_at"])
    op.create_index("idx_memory_usage_run", "ai_agent_memory_usage_events", ["run_id", "iteration", "step_index"])

    op.create_table(
        "ai_agent_memory_contradiction_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("memory_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=True),
        sa.Column("tool_call_id", sa.String(64), nullable=True),
        sa.Column("loop_observation_id", sa.String(64), nullable=True),
        sa.Column("contradiction_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("failure_fingerprint", sa.String(64), nullable=True),
        sa.Column("evidence_ref_json", sa.JSON(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["memory_id"], ["ai_project_memories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_agent_memory_contradiction_events_id", "ai_agent_memory_contradiction_events", ["id"])
    op.create_index("idx_memory_contradiction", "ai_agent_memory_contradiction_events", ["memory_id", "occurred_at"])
    op.create_index(
        "idx_memory_contradiction_fp",
        "ai_agent_memory_contradiction_events",
        ["memory_id", "failure_fingerprint"],
    )

    op.create_table(
        "ai_agent_memory_evidence_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("memory_id", sa.Integer(), nullable=False),
        sa.Column("evidence_ref_type", sa.String(64), nullable=False),
        sa.Column("evidence_ref_id", sa.String(128), nullable=False),
        sa.Column("evidence_version_id", sa.String(128), nullable=True),
        sa.Column("evidence_content_hash", sa.String(64), nullable=True),
        sa.Column("watch_id", sa.Integer(), nullable=True),
        sa.Column("link_role", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["memory_id"], ["ai_project_memories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_agent_memory_evidence_links_id", "ai_agent_memory_evidence_links", ["id"])
    op.create_index("idx_memory_evidence_link_memory", "ai_agent_memory_evidence_links", ["memory_id"])
    op.create_index(
        "idx_memory_evidence_link_ref",
        "ai_agent_memory_evidence_links",
        ["evidence_ref_type", "evidence_ref_id"],
    )


def downgrade() -> None:
    op.drop_table("ai_agent_memory_evidence_links")
    op.drop_table("ai_agent_memory_contradiction_events")
    op.drop_table("ai_agent_memory_usage_events")
    op.drop_table("ai_agent_memory_retrieval_profiles")
    op.drop_table("ai_agent_memory_source_profiles")
    op.drop_table("ai_project_memories")
