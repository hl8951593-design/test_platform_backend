from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AgentRuntimeSnapshot(Base):
    __tablename__ = "ai_agent_runtime_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_id", name="uq_agent_runtime_snapshots_snapshot_id"),
        UniqueConstraint("project_id", "runtime_hash", name="uq_agent_runtime_snapshots_project_hash"),
        Index("ix_agent_runtime_snapshot_project", "project_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    runtime_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_registry_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_bundle_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_bundle_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    policy_version_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tools_json: Mapped[list] = mapped_column(JSON, nullable=False)
    manifests_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    adapters_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    policies_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class AgentRun(Base):
    __tablename__ = "ai_agent_runs"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_agent_runs_run_id"),
        Index("ix_agent_runs_project_user", "project_id", "user_id", "created_at"),
        Index("ix_agent_runs_status", "status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    intent: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_iteration: Mapped[int] = mapped_column(default=0, nullable=False)
    current_step_index: Mapped[int] = mapped_column(default=0, nullable=False)
    max_iterations: Mapped[int] = mapped_column(default=3, nullable=False)
    runtime_snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    last_checkpoint_id: Mapped[int | None] = mapped_column(nullable=True)
    last_event_sequence: Mapped[int] = mapped_column(default=0, nullable=False)
    migration_block_count: Mapped[int] = mapped_column(default=0, nullable=False)
    blocking_tool_call_ids_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class AgentEvent(Base):
    __tablename__ = "ai_agent_events"
    __table_args__ = (
        UniqueConstraint("run_id", "event_seq", name="uq_agent_events_run_seq"),
        Index("ix_agent_events_run_seq", "run_id", "event_seq"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_seq: Mapped[int] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class AgentOutbox(Base):
    __tablename__ = "ai_agent_outbox"
    __table_args__ = (
        Index("ix_agent_outbox_status_retry", "status", "next_retry_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("ai_agent_events.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    publish_attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class AgentCheckpoint(Base):
    __tablename__ = "ai_agent_checkpoints"
    __table_args__ = (
        UniqueConstraint("run_id", "checkpoint_seq", name="uq_agent_checkpoints_run_seq"),
        Index("ix_agent_checkpoints_run_seq", "run_id", "checkpoint_seq"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    checkpoint_seq: Mapped[int] = mapped_column(nullable=False)
    runtime_snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    iteration: Mapped[int] = mapped_column(nullable=False)
    current_step_index: Mapped[int] = mapped_column(nullable=False)
    active_plan_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    active_draft_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_failure_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    recent_tool_call_ids_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    pending_approval_tool_call_ids_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    context_compaction_object_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    freshness_metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class AgentToolCall(Base):
    __tablename__ = "ai_agent_tool_calls"
    __table_args__ = (
        UniqueConstraint("tool_call_id", name="uq_agent_tool_calls_tool_call_id"),
        UniqueConstraint("idempotency_scope", "idempotency_key", name="uk_agent_tool_idem"),
        UniqueConstraint("run_id", "step_index", "attempt_index", name="uk_agent_tool_step"),
        Index("idx_agent_tool_status", "status", "lease_expires_at"),
        Index("idx_agent_tool_run", "run_id", "step_index"),
        Index("idx_agent_tool_backend", "backend_name", "backend_operation", "backend_contract_version"),
        Index("idx_agent_tool_context_build", "decision_context_build_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tool_call_id: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    step_index: Mapped[int] = mapped_column(nullable=False)
    attempt_index: Mapped[int] = mapped_column(nullable=False)
    runtime_snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_scope: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    base_side_effect_class: Mapped[str] = mapped_column(String(64), nullable=False)
    resolved_side_effect_class: Mapped[str] = mapped_column(String(64), nullable=False)
    base_replay_policy: Mapped[str] = mapped_column(String(64), nullable=False)
    resolved_replay_policy: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_reason_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_phase: Mapped[str | None] = mapped_column(String(32), nullable=True)
    effect_submission_state: Mapped[str] = mapped_column(String(64), nullable=False)
    effect_boundary_crossed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    downstream_send_intent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    downstream_request_observed_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    downstream_acceptance_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    downstream_acceptance_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_json_redacted: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_refs_json: Mapped[list] = mapped_column(JSON, nullable=False)
    policy_evidence_refs_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    audit_evidence_refs_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    evidence_mutability_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    decision_context_build_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_json_redacted: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_output_object_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    permission_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    required_permissions_json: Mapped[list] = mapped_column(JSON, nullable=False)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approval_scope_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approval_lineage_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approval_epoch: Mapped[int] = mapped_column(default=0, nullable=False)
    approved_approval_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    recovery_decision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    backend_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    backend_operation: Mapped[str | None] = mapped_column(String(128), nullable=True)
    backend_contract_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    backend_request_schema_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    backend_output_schema_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reconcile_contract_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_adapter_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    backend_effect_capability: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_resource_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    external_resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class AgentWorkerQueue(Base):
    __tablename__ = "ai_agent_worker_queue"
    __table_args__ = (
        UniqueConstraint("queue_id", name="uq_agent_worker_queue_queue_id"),
        Index("idx_agent_worker_queue_status", "status", "available_at", "priority"),
        Index("idx_agent_worker_queue_tool_call", "tool_call_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    queue_id: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_call_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[int] = mapped_column(default=100, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class AgentBackendContract(Base):
    __tablename__ = "ai_agent_backend_contracts"
    __table_args__ = (
        UniqueConstraint(
            "backend_name",
            "backend_operation",
            "backend_contract_version",
            name="uq_agent_backend_contract_operation",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    backend_name: Mapped[str] = mapped_column(String(128), nullable=False)
    backend_operation: Mapped[str] = mapped_column(String(128), nullable=False)
    backend_contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    request_schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reconcile_contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    result_adapter_version: Mapped[str] = mapped_column(String(64), nullable=False)
    effect_capability: Mapped[str] = mapped_column(String(64), nullable=False)
    compatibility_status: Mapped[str] = mapped_column(String(32), nullable=False)
    support_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    owner_team: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class AgentReconcileAttempt(Base):
    __tablename__ = "ai_agent_reconcile_attempts"
    __table_args__ = (
        UniqueConstraint("tool_call_id", "attempt_seq", name="uq_agent_reconcile_attempt_tool_seq"),
        Index("idx_agent_reconcile_attempt_tool", "tool_call_id", "attempt_seq"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tool_call_id: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_seq: Mapped[int] = mapped_column(nullable=False)
    backend_name: Mapped[str] = mapped_column(String(128), nullable=False)
    backend_operation: Mapped[str] = mapped_column(String(128), nullable=False)
    backend_contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    result_status: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_result_object_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class AgentMigrationBlock(Base):
    __tablename__ = "ai_agent_migration_blocks"
    __table_args__ = (
        UniqueConstraint("block_id", name="uq_agent_migration_blocks_block_id"),
        Index("idx_agent_migration_blocks_run_status", "run_id", "status", "created_at"),
        Index("idx_agent_migration_blocks_tool_call", "tool_call_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    block_id: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_call_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    block_type: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    backend_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    backend_operation: Mapped[str | None] = mapped_column(String(128), nullable=True)
    backend_contract_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    required_migration_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    resolution_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AgentApprovalLineage(Base):
    __tablename__ = "ai_agent_approval_lineages"
    __table_args__ = (
        UniqueConstraint("approval_lineage_id", name="uq_agent_approval_lineages_lineage_id"),
        Index("idx_agent_approval_lineages_tool_call", "tool_call_id"),
        Index("idx_agent_approval_lineages_run", "run_id", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    approval_lineage_id: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_call_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    current_epoch: Mapped[int] = mapped_column(default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    immutable_input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class AgentApproval(Base):
    __tablename__ = "ai_agent_approvals"
    __table_args__ = (
        UniqueConstraint("approval_id", name="uq_agent_approvals_approval_id"),
        UniqueConstraint("approval_lineage_id", "approval_epoch", name="uq_agent_approvals_lineage_epoch"),
        Index("idx_agent_approvals_tool_status", "tool_call_id", "approval_status"),
        Index("idx_agent_approvals_run_status", "run_id", "approval_status"),
        Index("idx_agent_approvals_lineage_status", "approval_lineage_id", "approval_status"),
        Index("idx_agent_approvals_expires", "approval_status", "expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    approval_id: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_lineage_id: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_epoch: Mapped[int] = mapped_column(nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_call_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    approval_status: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    required_permissions_json: Mapped[list] = mapped_column(JSON, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class AgentApprovalMutationLog(Base):
    __tablename__ = "ai_agent_approval_mutation_logs"
    __table_args__ = (
        Index("idx_agent_approval_mutation_logs_lineage", "approval_lineage_id", "created_at"),
        Index("idx_agent_approval_mutation_logs_tool_call", "tool_call_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    approval_lineage_id: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_call_id: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    mutation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    details_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class AgentContextBuild(Base):
    __tablename__ = "ai_agent_context_builds"
    __table_args__ = (
        UniqueConstraint("context_build_id", name="uq_agent_context_builds_context_build_id"),
        UniqueConstraint("run_id", "iteration", "step_index", "build_seq", name="uq_agent_context_builds_run_seq"),
        Index("idx_agent_context_builds_run", "run_id", "iteration", "step_index"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    context_build_id: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    iteration: Mapped[int] = mapped_column(nullable=False)
    step_index: Mapped[int] = mapped_column(nullable=False)
    build_seq: Mapped[int] = mapped_column(default=1, nullable=False)
    build_purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    token_budget: Mapped[int] = mapped_column(nullable=False)
    estimated_input_tokens: Mapped[int] = mapped_column(nullable=False)
    context_degradation_level: Mapped[str] = mapped_column(String(32), nullable=False)
    compressed_sections_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    omitted_evidence_refs_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    required_evidence_refs_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    required_evidence_complete: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    decision_quality_risk: Mapped[str] = mapped_column(String(32), default="low", nullable=False)
    prompt_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    build_metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class AgentLoopObservation(Base):
    __tablename__ = "ai_agent_loop_observations"
    __table_args__ = (
        UniqueConstraint("observation_id", name="uq_agent_loop_observations_observation_id"),
        Index("idx_agent_loop_observations_run", "run_id", "iteration", "step_index"),
        Index("idx_agent_loop_observations_context", "decision_context_build_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    observation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    iteration: Mapped[int] = mapped_column(nullable=False)
    step_index: Mapped[int] = mapped_column(nullable=False)
    decision_context_build_id: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_context_degradation_level: Mapped[str] = mapped_column(String(32), nullable=False)
    iteration_context_degradation_max: Mapped[str] = mapped_column(String(32), nullable=False)
    required_evidence_complete_for_decision: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    omitted_required_evidence_refs_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    next_action: Mapped[str] = mapped_column(String(64), nullable=False)
    next_action_is_high_risk: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    stop_action_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    stop_reasons_all_json: Mapped[list] = mapped_column(JSON, nullable=False)
    root_cause_primary: Mapped[str] = mapped_column(String(128), nullable=False)
    root_cause_rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    causal_chain_json: Mapped[list] = mapped_column(JSON, nullable=False)
    mitigation_action: Mapped[str] = mapped_column(String(128), nullable=False)
    observation_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class AgentEvidenceWatch(Base):
    __tablename__ = "ai_agent_evidence_watches"
    __table_args__ = (
        UniqueConstraint("evidence_watch_id", name="uq_agent_evidence_watches_watch_id"),
        Index("idx_agent_evidence_watch_ref", "ref_type", "ref_id", "watch_status"),
        Index("idx_agent_evidence_watch_run", "run_id", "watch_status"),
        Index("idx_agent_evidence_watch_ref_id", "evidence_ref_id", "watch_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    evidence_watch_id: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_call_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_ref_id: Mapped[str] = mapped_column(String(128), nullable=False)
    ref_type: Mapped[str] = mapped_column(String(64), nullable=False)
    ref_id: Mapped[str] = mapped_column(String(128), nullable=False)
    watched_version_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    watched_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    watch_status: Mapped[str] = mapped_column(String(32), nullable=False)
    stale_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    stale_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    stale_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AgentRootCauseRule(Base):
    __tablename__ = "ai_agent_root_cause_rules"
    __table_args__ = (
        UniqueConstraint("rule_id", name="uq_agent_root_cause_rules_rule_id"),
        Index("idx_agent_root_cause_rules_status", "status", "priority"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_key: Mapped[str] = mapped_column(String(128), nullable=False)
    root_cause_primary: Mapped[str] = mapped_column(String(128), nullable=False)
    causal_chain_json: Mapped[list] = mapped_column(JSON, nullable=False)
    mitigation_action: Mapped[str] = mapped_column(String(128), nullable=False)
    priority: Mapped[int] = mapped_column(nullable=False)
    priority_band: Mapped[str] = mapped_column(String(32), nullable=False)
    match_expression_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class ProjectMemory(Base):
    __tablename__ = "ai_project_memories"
    __table_args__ = (
        Index("idx_memory_retrieval", "project_id", "memory_type", "status", "confidence", "stale_score"),
        Index("idx_memory_source", "project_id", "source_type", "status"),
        Index("idx_memory_hash", "project_id", "content_hash"),
        Index("idx_memory_stale", "project_id", "status", "stale_score", "updated_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    memory_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    memory_version: Mapped[int] = mapped_column(default=1, nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_ref_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    authority: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    initial_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_reason_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    contradiction_count: Mapped[int] = mapped_column(default=0, nullable=False)
    recent_contradiction_count: Mapped[int] = mapped_column(default=0, nullable=False)
    validation_count: Mapped[int] = mapped_column(default=0, nullable=False)
    recent_validation_count: Mapped[int] = mapped_column(default=0, nullable=False)
    last_contradicted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_failure_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    max_recent_severity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stale_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    stale_reason_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    evidence_refs_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    watched_refs_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class AgentMemorySourceProfile(Base):
    __tablename__ = "ai_agent_memory_source_profiles"
    __table_args__ = (
        UniqueConstraint("source_type", name="uq_agent_memory_source_profiles_source_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    initial_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    authority: Mapped[str] = mapped_column(String(64), nullable=False)
    default_ttl_days: Mapped[int | None] = mapped_column(nullable=True)
    requires_source_ref: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    requires_content_hash: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allowed_for_high_risk: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class AgentMemoryRetrievalProfile(Base):
    __tablename__ = "ai_agent_memory_retrieval_profiles"
    __table_args__ = (
        UniqueConstraint("profile_name", name="uq_agent_memory_retrieval_profiles_name"),
        Index("idx_agent_memory_retrieval_profiles_status", "status", "profile_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    profile_name: Mapped[str] = mapped_column(String(64), nullable=False)
    task_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False)
    min_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    max_stale_score: Mapped[float] = mapped_column(Float, nullable=False)
    allow_memory_for_high_risk: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    semantic_weight: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_weight: Mapped[float] = mapped_column(Float, nullable=False)
    recency_weight: Mapped[float] = mapped_column(Float, nullable=False)
    authority_weight: Mapped[float] = mapped_column(Float, nullable=False)
    validation_weight: Mapped[float] = mapped_column(Float, nullable=False)
    stale_weight: Mapped[float] = mapped_column(Float, nullable=False)
    contradiction_weight: Mapped[float] = mapped_column(Float, nullable=False)
    max_contradiction_penalty: Mapped[float] = mapped_column(Float, nullable=False)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class AgentMemoryUsageEvent(Base):
    __tablename__ = "ai_agent_memory_usage_events"
    __table_args__ = (
        Index("idx_memory_usage_memory", "memory_id", "created_at"),
        Index("idx_memory_usage_run", "run_id", "iteration", "step_index"),
        Index("idx_memory_usage_feedback", "feedback_state", "outcome", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    memory_id: Mapped[int] = mapped_column(ForeignKey("ai_project_memories.id"), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    iteration: Mapped[int | None] = mapped_column(nullable=True)
    step_index: Mapped[int | None] = mapped_column(nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    context_build_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retrieval_profile: Mapped[str] = mapped_column(String(64), nullable=False)
    retrieval_score: Mapped[float] = mapped_column(Float, nullable=False)
    usage_role: Mapped[str] = mapped_column(String(64), nullable=False)
    active_for_policy: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    caused_tool_input_change: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_ref_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    feedback_state: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    feedback_processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    feedback_result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class AgentMemoryContradictionEvent(Base):
    __tablename__ = "ai_agent_memory_contradiction_events"
    __table_args__ = (
        Index("idx_memory_contradiction", "memory_id", "occurred_at"),
        Index("idx_memory_contradiction_fp", "memory_id", "failure_fingerprint"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    memory_id: Mapped[int] = mapped_column(ForeignKey("ai_project_memories.id"), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    loop_observation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contradiction_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_ref_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class AgentMemoryEvidenceLink(Base):
    __tablename__ = "ai_agent_memory_evidence_links"
    __table_args__ = (
        Index("idx_memory_evidence_link_memory", "memory_id"),
        Index("idx_memory_evidence_link_ref", "evidence_ref_type", "evidence_ref_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    memory_id: Mapped[int] = mapped_column(ForeignKey("ai_project_memories.id"), nullable=False)
    evidence_ref_type: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_ref_id: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_version_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    evidence_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    watch_id: Mapped[int | None] = mapped_column(nullable=True)
    link_role: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
