"""add agent loop evidence foundation

Revision ID: 0024_agent_loop_evidence_foundation
Revises: 0023_agent_approval_foundation
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0024_agent_loop_evidence_foundation"
down_revision: str | Sequence[str] | None = "0023_agent_approval_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_agent_tool_calls", sa.Column("policy_evidence_refs_json", sa.JSON(), nullable=True))
    op.add_column("ai_agent_tool_calls", sa.Column("audit_evidence_refs_json", sa.JSON(), nullable=True))
    op.add_column("ai_agent_tool_calls", sa.Column("evidence_mutability_summary_json", sa.JSON(), nullable=True))
    op.add_column("ai_agent_tool_calls", sa.Column("decision_context_build_id", sa.String(64), nullable=True))
    op.create_index("idx_agent_tool_context_build", "ai_agent_tool_calls", ["decision_context_build_id"])

    op.create_table(
        "ai_agent_context_builds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("context_build_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("build_seq", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("build_purpose", sa.String(64), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=True),
        sa.Column("token_budget", sa.Integer(), nullable=False),
        sa.Column("estimated_input_tokens", sa.Integer(), nullable=False),
        sa.Column("context_degradation_level", sa.String(32), nullable=False),
        sa.Column("compressed_sections_json", sa.JSON(), nullable=True),
        sa.Column("omitted_evidence_refs_json", sa.JSON(), nullable=True),
        sa.Column("required_evidence_refs_json", sa.JSON(), nullable=True),
        sa.Column("required_evidence_complete", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("decision_quality_risk", sa.String(32), nullable=False, server_default="low"),
        sa.Column("prompt_object_key", sa.String(512), nullable=True),
        sa.Column("prompt_hash", sa.String(64), nullable=True),
        sa.Column("build_metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("context_build_id", name="uq_agent_context_builds_context_build_id"),
        sa.UniqueConstraint("run_id", "iteration", "step_index", "build_seq", name="uq_agent_context_builds_run_seq"),
    )
    op.create_index("ix_ai_agent_context_builds_id", "ai_agent_context_builds", ["id"])
    op.create_index("idx_agent_context_builds_run", "ai_agent_context_builds", ["run_id", "iteration", "step_index"])

    op.create_table(
        "ai_agent_loop_observations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("observation_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("decision_context_build_id", sa.String(64), nullable=False),
        sa.Column("decision_context_degradation_level", sa.String(32), nullable=False),
        sa.Column("iteration_context_degradation_max", sa.String(32), nullable=False),
        sa.Column("required_evidence_complete_for_decision", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("omitted_required_evidence_refs_json", sa.JSON(), nullable=True),
        sa.Column("next_action", sa.String(64), nullable=False),
        sa.Column("next_action_is_high_risk", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("stop_action_reason", sa.String(128), nullable=True),
        sa.Column("stop_reasons_all_json", sa.JSON(), nullable=False),
        sa.Column("root_cause_primary", sa.String(128), nullable=False),
        sa.Column("root_cause_rule_id", sa.String(64), nullable=False),
        sa.Column("causal_chain_json", sa.JSON(), nullable=False),
        sa.Column("mitigation_action", sa.String(128), nullable=False),
        sa.Column("observation_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("observation_id", name="uq_agent_loop_observations_observation_id"),
    )
    op.create_index("ix_ai_agent_loop_observations_id", "ai_agent_loop_observations", ["id"])
    op.create_index(
        "idx_agent_loop_observations_run",
        "ai_agent_loop_observations",
        ["run_id", "iteration", "step_index"],
    )
    op.create_index(
        "idx_agent_loop_observations_context",
        "ai_agent_loop_observations",
        ["decision_context_build_id"],
    )

    op.create_table(
        "ai_agent_evidence_watches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("evidence_watch_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("tool_call_id", sa.String(64), nullable=True),
        sa.Column("evidence_ref_id", sa.String(128), nullable=False),
        sa.Column("ref_type", sa.String(64), nullable=False),
        sa.Column("ref_id", sa.String(128), nullable=False),
        sa.Column("watched_version_id", sa.String(128), nullable=True),
        sa.Column("watched_content_hash", sa.String(64), nullable=True),
        sa.Column("watch_status", sa.String(32), nullable=False),
        sa.Column("stale_reason", sa.String(128), nullable=True),
        sa.Column("stale_event_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("stale_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evidence_watch_id", name="uq_agent_evidence_watches_watch_id"),
    )
    op.create_index("ix_ai_agent_evidence_watches_id", "ai_agent_evidence_watches", ["id"])
    op.create_index(
        "idx_agent_evidence_watch_ref",
        "ai_agent_evidence_watches",
        ["ref_type", "ref_id", "watch_status"],
    )
    op.create_index("idx_agent_evidence_watch_run", "ai_agent_evidence_watches", ["run_id", "watch_status"])
    op.create_index(
        "idx_agent_evidence_watch_ref_id",
        "ai_agent_evidence_watches",
        ["evidence_ref_id", "watch_status"],
    )

    op.create_table(
        "ai_agent_root_cause_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.String(64), nullable=False),
        sa.Column("reason_key", sa.String(128), nullable=False),
        sa.Column("root_cause_primary", sa.String(128), nullable=False),
        sa.Column("causal_chain_json", sa.JSON(), nullable=False),
        sa.Column("mitigation_action", sa.String(128), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("priority_band", sa.String(32), nullable=False),
        sa.Column("match_expression_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_id", name="uq_agent_root_cause_rules_rule_id"),
    )
    op.create_index("ix_ai_agent_root_cause_rules_id", "ai_agent_root_cause_rules", ["id"])
    op.create_index("idx_agent_root_cause_rules_status", "ai_agent_root_cause_rules", ["status", "priority"])


def downgrade() -> None:
    op.drop_table("ai_agent_root_cause_rules")
    op.drop_table("ai_agent_evidence_watches")
    op.drop_table("ai_agent_loop_observations")
    op.drop_table("ai_agent_context_builds")
    op.drop_index("idx_agent_tool_context_build", table_name="ai_agent_tool_calls")
    op.drop_column("ai_agent_tool_calls", "decision_context_build_id")
    op.drop_column("ai_agent_tool_calls", "evidence_mutability_summary_json")
    op.drop_column("ai_agent_tool_calls", "audit_evidence_refs_json")
    op.drop_column("ai_agent_tool_calls", "policy_evidence_refs_json")
