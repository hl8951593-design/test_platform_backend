"""create agent runtime foundation tables

Revision ID: 0021_agent_runtime_foundation
Revises: 0020_scenario_nodes
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0021_agent_runtime_foundation"
down_revision: str | Sequence[str] | None = "0020_scenario_nodes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_agent_runtime_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("runtime_hash", sa.String(64), nullable=False),
        sa.Column("tool_registry_hash", sa.String(64), nullable=False),
        sa.Column("manifest_bundle_hash", sa.String(64), nullable=False),
        sa.Column("prompt_bundle_hash", sa.String(64), nullable=True),
        sa.Column("policy_version_hash", sa.String(64), nullable=True),
        sa.Column("tools_json", sa.JSON(), nullable=False),
        sa.Column("manifests_json", sa.JSON(), nullable=False),
        sa.Column("adapters_json", sa.JSON(), nullable=True),
        sa.Column("policies_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "runtime_hash", name="uq_agent_runtime_snapshots_project_hash"),
        sa.UniqueConstraint("snapshot_id", name="uq_agent_runtime_snapshots_snapshot_id"),
    )
    op.create_index("ix_ai_agent_runtime_snapshots_id", "ai_agent_runtime_snapshots", ["id"])
    op.create_index(
        "ix_agent_runtime_snapshot_project",
        "ai_agent_runtime_snapshots",
        ["project_id", "created_at"],
    )

    op.create_table(
        "ai_agent_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.String(64), nullable=True),
        sa.Column("intent", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_iteration", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_step_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_iterations", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("runtime_snapshot_id", sa.String(64), nullable=False),
        sa.Column("last_checkpoint_id", sa.Integer(), nullable=True),
        sa.Column("last_event_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_agent_runs_run_id"),
    )
    op.create_index("ix_ai_agent_runs_id", "ai_agent_runs", ["id"])
    op.create_index("ix_agent_runs_project_user", "ai_agent_runs", ["project_id", "user_id", "created_at"])
    op.create_index("ix_agent_runs_status", "ai_agent_runs", ["status", "updated_at"])

    op.create_table(
        "ai_agent_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("event_seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "event_seq", name="uq_agent_events_run_seq"),
    )
    op.create_index("ix_ai_agent_events_id", "ai_agent_events", ["id"])
    op.create_index("ix_agent_events_run_seq", "ai_agent_events", ["run_id", "event_seq"])

    op.create_table(
        "ai_agent_outbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("publish_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["ai_agent_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_agent_outbox_id", "ai_agent_outbox", ["id"])
    op.create_index("ix_agent_outbox_status_retry", "ai_agent_outbox", ["status", "next_retry_at"])

    op.create_table(
        "ai_agent_checkpoints",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("checkpoint_seq", sa.Integer(), nullable=False),
        sa.Column("runtime_snapshot_id", sa.String(64), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("current_step_index", sa.Integer(), nullable=False),
        sa.Column("active_plan_summary_json", sa.JSON(), nullable=True),
        sa.Column("active_draft_summary_json", sa.JSON(), nullable=True),
        sa.Column("last_failure_summary_json", sa.JSON(), nullable=True),
        sa.Column("recent_tool_call_ids_json", sa.JSON(), nullable=True),
        sa.Column("pending_approval_tool_call_ids_json", sa.JSON(), nullable=True),
        sa.Column("context_compaction_object_key", sa.String(256), nullable=True),
        sa.Column("freshness_metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "checkpoint_seq", name="uq_agent_checkpoints_run_seq"),
    )
    op.create_index("ix_ai_agent_checkpoints_id", "ai_agent_checkpoints", ["id"])
    op.create_index("ix_agent_checkpoints_run_seq", "ai_agent_checkpoints", ["run_id", "checkpoint_seq"])

    op.create_table(
        "ai_agent_tool_calls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tool_call_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("attempt_index", sa.Integer(), nullable=False),
        sa.Column("runtime_snapshot_id", sa.String(64), nullable=False),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("tool_version", sa.String(32), nullable=False),
        sa.Column("schema_hash", sa.String(64), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("idempotency_scope", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("base_side_effect_class", sa.String(64), nullable=False),
        sa.Column("resolved_side_effect_class", sa.String(64), nullable=False),
        sa.Column("base_replay_policy", sa.String(64), nullable=False),
        sa.Column("resolved_replay_policy", sa.String(64), nullable=False),
        sa.Column("policy_reason_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("execution_phase", sa.String(32), nullable=True),
        sa.Column("effect_submission_state", sa.String(64), nullable=False),
        sa.Column("effect_boundary_crossed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("downstream_send_intent_at", sa.DateTime(), nullable=True),
        sa.Column("downstream_request_observed_sent_at", sa.DateTime(), nullable=True),
        sa.Column("downstream_acceptance_id", sa.String(128), nullable=True),
        sa.Column("downstream_acceptance_at", sa.DateTime(), nullable=True),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("input_json_redacted", sa.JSON(), nullable=False),
        sa.Column("evidence_refs_json", sa.JSON(), nullable=False),
        sa.Column("output_hash", sa.String(64), nullable=True),
        sa.Column("output_json_redacted", sa.JSON(), nullable=True),
        sa.Column("raw_output_object_key", sa.String(256), nullable=True),
        sa.Column("permission_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("required_permissions_json", sa.JSON(), nullable=False),
        sa.Column("approval_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approval_scope_hash", sa.String(64), nullable=True),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("recovery_decision", sa.String(64), nullable=True),
        sa.Column("backend_name", sa.String(128), nullable=True),
        sa.Column("backend_operation", sa.String(128), nullable=True),
        sa.Column("backend_contract_version", sa.String(64), nullable=True),
        sa.Column("backend_effect_capability", sa.String(64), nullable=True),
        sa.Column("external_resource_type", sa.String(128), nullable=True),
        sa.Column("external_resource_id", sa.String(128), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_scope", "idempotency_key", name="uk_agent_tool_idem"),
        sa.UniqueConstraint("run_id", "step_index", "attempt_index", name="uk_agent_tool_step"),
        sa.UniqueConstraint("tool_call_id", name="uq_agent_tool_calls_tool_call_id"),
    )
    op.create_index("ix_ai_agent_tool_calls_id", "ai_agent_tool_calls", ["id"])
    op.create_index("idx_agent_tool_status", "ai_agent_tool_calls", ["status", "lease_expires_at"])
    op.create_index("idx_agent_tool_run", "ai_agent_tool_calls", ["run_id", "step_index"])
    op.create_index(
        "idx_agent_tool_backend",
        "ai_agent_tool_calls",
        ["backend_name", "backend_operation", "backend_contract_version"],
    )

    op.create_table(
        "ai_agent_worker_queue",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("queue_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("tool_call_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("queue_id", name="uq_agent_worker_queue_queue_id"),
    )
    op.create_index("ix_ai_agent_worker_queue_id", "ai_agent_worker_queue", ["id"])
    op.create_index("idx_agent_worker_queue_status", "ai_agent_worker_queue", ["status", "available_at", "priority"])
    op.create_index("idx_agent_worker_queue_tool_call", "ai_agent_worker_queue", ["tool_call_id"])

    op.create_table(
        "ai_agent_backend_contracts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("backend_name", sa.String(128), nullable=False),
        sa.Column("backend_operation", sa.String(128), nullable=False),
        sa.Column("backend_contract_version", sa.String(64), nullable=False),
        sa.Column("request_schema_hash", sa.String(64), nullable=False),
        sa.Column("output_schema_hash", sa.String(64), nullable=False),
        sa.Column("reconcile_contract_version", sa.String(64), nullable=False),
        sa.Column("result_adapter_version", sa.String(64), nullable=False),
        sa.Column("effect_capability", sa.String(64), nullable=False),
        sa.Column("compatibility_status", sa.String(32), nullable=False),
        sa.Column("support_until", sa.DateTime(), nullable=True),
        sa.Column("owner_team", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "backend_name",
            "backend_operation",
            "backend_contract_version",
            name="uq_agent_backend_contract_operation",
        ),
    )
    op.create_index("ix_ai_agent_backend_contracts_id", "ai_agent_backend_contracts", ["id"])

    op.create_table(
        "ai_agent_reconcile_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tool_call_id", sa.String(64), nullable=False),
        sa.Column("attempt_seq", sa.Integer(), nullable=False),
        sa.Column("backend_name", sa.String(128), nullable=False),
        sa.Column("backend_operation", sa.String(128), nullable=False),
        sa.Column("backend_contract_version", sa.String(64), nullable=False),
        sa.Column("result_status", sa.String(64), nullable=False),
        sa.Column("raw_result_object_key", sa.String(256), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(512), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tool_call_id", "attempt_seq", name="uq_agent_reconcile_attempt_tool_seq"),
    )
    op.create_index("ix_ai_agent_reconcile_attempts_id", "ai_agent_reconcile_attempts", ["id"])
    op.create_index("idx_agent_reconcile_attempt_tool", "ai_agent_reconcile_attempts", ["tool_call_id", "attempt_seq"])


def downgrade() -> None:
    op.drop_table("ai_agent_reconcile_attempts")
    op.drop_table("ai_agent_backend_contracts")
    op.drop_table("ai_agent_worker_queue")
    op.drop_table("ai_agent_tool_calls")
    op.drop_table("ai_agent_checkpoints")
    op.drop_table("ai_agent_outbox")
    op.drop_table("ai_agent_events")
    op.drop_table("ai_agent_runs")
    op.drop_table("ai_agent_runtime_snapshots")
