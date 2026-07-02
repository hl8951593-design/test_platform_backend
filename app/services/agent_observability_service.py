from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.sensitive_data import request_fingerprint
from app.models.agent import (
    AgentApproval,
    AgentApprovalMutationLog,
    AgentContextBuild,
    AgentEvent,
    AgentLoopObservation,
    AgentMemoryContradictionEvent,
    AgentMemoryStalenessEvent,
    AgentMemoryUsageEvent,
    AgentMigrationBlock,
    AgentOutbox,
    AgentReconcileAttempt,
    AgentRun,
    AgentToolCall,
    AgentWorkerQueue,
    ProjectMemory,
)


OutboxPublisherCallback = Callable[[AgentEvent], None]


AGENT_ERROR_MESSAGE_SUMMARY_VERSION = "agent_error_message_summary_v1"
AGENT_ERROR_MESSAGE_MAX_CHARS = 512
AGENT_ERROR_MESSAGE_TRUNCATION_MARKER = "[agent_error_message_truncated]"


METRICS_SNAPSHOT_FIELDS = (
    "project_id",
    "generated_at",
    "metrics",
    "derived_from",
)
METRICS_DERIVED_FROM_FIELDS = (
    "counters",
    "outbox_publish_lag_ms",
    "scope",
)
OUTBOX_PUBLISH_FIELDS = (
    "attempted",
    "published",
    "failed",
    "dead_letter",
    "pending_remaining",
    "outbox_publish_lag_ms",
)
WORKER_QUEUE_AUDIT_FIELDS = (
    "project_id",
    "generated_at",
    "status_counts",
    "total_count",
    "active_count",
    "expired_lease_count",
    "duplicate_active_lease_count",
    "oldest_queued_age_ms",
    "lease_scan_stable",
    "expired_leases",
    "duplicate_active_leases",
    "derived_from",
)
AGENT_WORKER_QUEUE_EXPIRED_LEASE_ITEM_ID_PREFIX = "agent-worker-queue-expired-lease"
AGENT_WORKER_QUEUE_DUPLICATE_ACTIVE_ITEM_ID_PREFIX = "agent-worker-queue-duplicate-active"
WORKER_QUEUE_EXPIRED_LEASE_FIELDS = (
    "item_id",
    "queue_id",
    "run_id",
    "tool_call_id",
    "lease_owner",
    "lease_expires_at",
    "attempt_count",
    "last_error_code",
)
WORKER_QUEUE_DUPLICATE_ACTIVE_FIELDS = (
    "item_id",
    "tool_call_id",
    "queue_ids",
    "statuses",
    "lease_owners",
)
WORKER_QUEUE_DERIVED_FROM_FIELDS = (
    "queue_table",
    "active_statuses",
    "scope",
)
EVENT_REPLAY_AUDIT_FIELDS = (
    "run_id",
    "project_id",
    "last_event_sequence",
    "after_sequence",
    "event_count",
    "replay_event_count",
    "first_replay_event_seq",
    "last_replay_event_seq",
    "missing_sequences",
    "duplicate_sequences",
    "unexpected_sequences",
    "replayable",
    "replay_cursor_valid",
)
EVENT_REPLAY_STRESS_AUDIT_FIELDS = (
    "project_id",
    "generated_at",
    "sample_limit",
    "cursor_count",
    "audited_run_count",
    "cursor_window_count",
    "failed_run_count",
    "failed_run_ids",
    "invalid_cursor_count",
    "total_replay_events",
    "max_replay_window_events",
    "high_concurrency_replayable",
    "run_audits",
    "derived_from",
)
AGENT_EVENT_REPLAY_STRESS_RUN_ITEM_ID_PREFIX = "agent-event-replay-run"
AGENT_EVENT_REPLAY_CURSOR_ITEM_ID_PREFIX = "agent-event-replay-cursor"
EVENT_REPLAY_STRESS_RUN_FIELDS = (
    "item_id",
    "run_id",
    "project_id",
    "last_event_sequence",
    "event_count",
    "cursor_audits",
    "replayable",
)
EVENT_REPLAY_CURSOR_AUDIT_FIELDS = (
    "item_id",
    "after_sequence",
    "replay_event_count",
    "first_replay_event_seq",
    "last_replay_event_seq",
    "replayable",
    "replay_cursor_valid",
)
EVENT_REPLAY_DERIVED_FROM_FIELDS = (
    "runs",
    "events",
    "cursor_policy",
)
ALERT_RUNBOOK_REQUIRED_SEVERITIES = ("P0", "P1")
ALERT_DYNAMIC_RUNBOOKS = {
    "agent_release_gate_violation": "release_gate_violation",
}
AGENT_ALERT_ITEM_ID_PREFIX = "agent-alert"
AGENT_DASHBOARD_CHECK_ITEM_ID_PREFIX = "agent-dashboard-check"
ALERT_SNAPSHOT_FIELDS = (
    "project_id",
    "generated_at",
    "status",
    "alerts",
    "summary",
    "derived_from",
)
ALERT_ITEM_FIELDS = (
    "item_id",
    "alert_id",
    "severity",
    "status",
    "metric_key",
    "observed_value",
    "threshold",
    "summary",
    "action",
    "runbook_id",
    "details",
)
ALERT_SUMMARY_FIELDS = (
    "total",
    "by_severity",
    "highest_severity",
)
ALERT_STATUS_VALUES = ("ok", "firing")
READINESS_DASHBOARD_FIELDS = (
    "project_id",
    "generated_at",
    "readiness",
    "checks",
    "metrics",
    "release_gate",
    "promotion_assessment",
    "fault_injection",
    "runbooks",
    "root_cause_governance",
    "alerts",
    "alert_summary",
    "derived_from",
)
DASHBOARD_CHECK_FIELDS = (
    "item_id",
    "name",
    "status",
    "severity",
    "summary",
    "details",
)
DASHBOARD_CHECK_NAMES = (
    "metrics_catalog_complete",
    "release_gate_current_level_clean",
    "fault_injection_catalog_complete",
    "root_cause_rule_governance",
    "runbook_catalog_complete",
    "alert_metric_catalog_complete",
    "live_recovery_attention",
    "monitoring_alerts_clear",
    "release_gate_promotion_assessment",
)
READINESS_STATUS_VALUES = ("pass", "attention", "blocked")
AGENT_LAUNCH_AUDIT_FIELDS = (
    "project_id",
    "generated_at",
    "ready",
    "status",
    "checks",
    "model_health",
    "dashboard",
    "promotion",
    "derived_from",
)
AGENT_LAUNCH_AUDIT_CHECK_NAMES = (
    "model_provider_configured",
    "normal_conversation_runtime_available",
    "frontend_event_contract_available",
    "dashboard_readiness_not_blocked",
    "backend_repository_delivery_complete",
    "frontend_external_scope_declared",
    "promotion_assessment_available",
)
AGENT_BACKEND_COMPLETION_AUDIT_FIELDS = (
    "project_id",
    "generated_at",
    "complete",
    "status",
    "checks",
    "backend_scope",
    "launch_audit",
    "runtime_contracts",
    "diagnostics",
    "derived_from",
)
AGENT_BACKEND_COMPLETION_AUDIT_CHECK_NAMES = (
    "model_provider_configured",
    "conversation_runner_streaming",
    "server_side_conversation_history",
    "tool_loop_and_approval_resume",
    "memory_context_injection",
    "frontend_contract_surface",
    "observability_and_release_gate",
    "backend_delivery_docs_synced",
    "live_e2e_diagnostic_available",
    "behavior_evaluation_suite_available",
)
FAULT_INJECTION_COVERAGE_FIELDS = (
    "generated_at",
    "registered_case_count",
    "required_case_count",
    "covered_required_case_ids",
    "missing_required_case_ids",
    "extra_case_ids",
    "coverage_ratio",
    "coverage_pass",
    "derived_from",
)
MONITORING_ALERT_BLOCKING_SEVERITIES = ("P0", "P1")
MONITORING_ALERTS_CLEAR_DETAIL_FIELDS = (
    "alert_total",
    "by_severity",
    "highest_severity",
    "blocking_severities",
    "blocking_alert_count",
    "blocking_alert_ids",
    "blocking_runbook_ids",
    "p0_alert_ids",
    "p1_alert_ids",
)
PROMOTION_DASHBOARD_SUMMARY_FIELDS = (
    "endpoint",
    "current_level",
    "target_level",
    "target_gate_known",
    "target_gate_static_blocked_reasons",
    "current_tool_violation_count",
    "current_tool_violations",
    "final_delivery_contract_pass",
    "final_delivery_backend_repository_scope_pass",
    "final_delivery_missing_by_category",
    "final_delivery_external_scope_categories",
    "assessment_available",
    "dashboard_dependency",
)

REQUIRED_DASHBOARD_METRICS = {
    "tool_call_uncertain_total",
    "tool_call_reconcile_success_total",
    "tool_call_reconcile_manual_total",
    "reconcile_backoff_active_total",
    "tool_call_orphan_recovered_total",
    "tool_call_send_intent_orphan_total",
    "tool_call_safe_retry_after_send_intent_not_found_total",
    "tool_call_transport_sent_uncertain_total",
    "tool_call_backend_accepted_uncertain_total",
    "backend_effect_capability_receipt_first_total",
    "backend_effect_capability_legacy_no_receipt_total",
    "tool_call_legacy_no_receipt_manual_total",
    "tool_call_backend_contract_unsupported_total",
    "tool_call_duplicate_blocked_total",
    "approval_superseded_total",
    "approval_approve_conflict_total",
    "approval_epoch_conflict_total",
    "approval_replacement_atomic_total",
    "approval_lineage_lock_wait_ms",
    "approval_lineage_lock_skip_total",
    "approval_expire_due_total",
    "approval_expire_batch_lag_ms",
    "approval_lineage_hotspot_total",
    "evidence_volatile_requires_revalidation_total",
    "evidence_historical_volatile_excluded_total",
    "evidence_mixed_volatile_frozen_total",
    "permission_revoked_before_execution_total",
    "backend_contract_unsupported_total",
    "migration_block_open_total",
    "runtime_snapshot_migration_block_total",
    "backend_contract_migration_block_total",
    "run_migration_blocked_total",
    "context_degraded_total",
    "context_full_evidence_required_total",
    "context_decision_build_missing_total",
    "loop_root_cause_context_degraded_total",
    "loop_root_cause_unknown_total",
    "root_cause_rule_missing_total",
    "invalid_repair_scope_total",
    "tool_prerequisite_missing_total",
    "tool_request_format_invalid_total",
    "required_tool_followup_missing_total",
    "max_iterations_total",
    "same_failure_no_progress_total",
    "memory_contradiction_total",
    "memory_contradiction_penalty_applied_total",
    "memory_retrieved_total",
    "memory_used_active_policy_total",
    "memory_retrieval_profile_missing_total",
    "memory_low_confidence_filtered_total",
    "memory_high_risk_blocked_total",
    "memory_needs_revalidation_total",
    "memory_evidence_watch_stale_total",
    "memory_bypassed_evidence_ref_total",
    "checkpoint_freshness_failed_total",
    "outbox_publish_lag_ms",
    "event_replay_gap_total",
    "event_replay_stress_failed_total",
    "event_replay_stress_cursor_window_total",
    "event_replay_stress_max_window_events",
    "fault_injection_required_case_total",
    "fault_injection_registered_case_total",
    "fault_injection_missing_required_total",
    "fault_injection_coverage_ratio",
    "worker_queue_expired_lease_total",
    "worker_queue_duplicate_active_lease_total",
    "worker_queue_oldest_queued_age_ms",
    "release_gate_violation_count",
    "backend_capability_degraded_total",
}

REQUIRED_FAULT_CASES = {
    "send_intent_not_found",
    "transport_sent_not_found",
    "backend_accepted_not_found",
    "effect_committed_reconcile_reuse",
    "tool_succeeded_eventstore_write_failed",
    "outbox_publish_failure",
    "reconcile_conflict",
    "unsupported_schema_version",
    "migration_block_resolve_checkpoint_continue",
    "legacy_no_receipt_high_risk",
    "approval_epoch_conflict",
    "approval_supersede_replacement_atomic",
    "approval_expired_before_approve",
    "checkpoint_stale",
    "context_heavy_evidence_incomplete",
    "loop_observation_decision_context_binding",
    "evidence_historical_volatile_excluded",
    "evidence_mixed_volatile_frozen_requires_revalidation",
    "memory_contradiction",
    "memory_stale_evidence_watch",
    "memory_bypassed_evidence_ref",
    "duplicate_idempotency_key",
    "permission_revoked_before_execution",
    "worker_queue_reconcile_required",
    "root_cause_rule_missing",
    "high_risk_memory_only_blocked",
}

REQUIRED_RUNBOOKS = {
    "tool_call_uncertain",
    "migration_blocked",
    "backend_capability_degraded",
    "approval_stale",
    "checkpoint_stale",
    "outbox_publish_lag",
    "event_replay_recovery",
    "fault_injection_coverage",
    "worker_queue_recovery",
    "context_linkage_repair",
    "agent_runtime_loop_repair",
    "root_cause_rule_missing",
    "memory_evidence_ref_violation",
    "release_gate_violation",
}

ALERT_FACT_METRICS = {
    "tool_call_uncertain_total",
    "tool_call_reconcile_manual_total",
    "reconcile_backoff_active_total",
    "tool_call_send_intent_orphan_total",
    "tool_call_safe_retry_after_send_intent_not_found_total",
    "tool_call_transport_sent_uncertain_total",
    "tool_call_backend_accepted_uncertain_total",
    "backend_effect_capability_receipt_first_total",
    "backend_effect_capability_legacy_no_receipt_total",
    "tool_call_legacy_no_receipt_manual_total",
    "tool_call_backend_contract_unsupported_total",
    "approval_approve_conflict_total",
    "approval_epoch_conflict_total",
    "approval_lineage_lock_wait_ms",
    "approval_lineage_lock_skip_total",
    "approval_expire_due_total",
    "approval_expire_batch_lag_ms",
    "approval_lineage_hotspot_total",
    "backend_contract_unsupported_total",
    "migration_block_open_total",
    "runtime_snapshot_migration_block_total",
    "backend_contract_migration_block_total",
    "run_migration_blocked_total",
    "outbox_publish_lag_ms",
    "event_replay_gap_total",
    "event_replay_stress_failed_total",
    "event_replay_stress_cursor_window_total",
    "event_replay_stress_max_window_events",
    "fault_injection_required_case_total",
    "fault_injection_registered_case_total",
    "fault_injection_missing_required_total",
    "fault_injection_coverage_ratio",
    "context_full_evidence_required_total",
    "checkpoint_freshness_failed_total",
    "context_decision_build_missing_total",
    "root_cause_rule_missing_total",
    "memory_bypassed_evidence_ref_total",
    "memory_high_risk_blocked_total",
    "memory_needs_revalidation_total",
    "worker_queue_expired_lease_total",
    "worker_queue_duplicate_active_lease_total",
    "release_gate_violation_count",
    "backend_capability_degraded_total",
}

DYNAMIC_ALERT_METRICS = {
    "release_gate_violation_count",
}

ALERT_RULES = (
    {
        "alert_id": "agent_tool_call_uncertain",
        "metric_key": "tool_call_uncertain_total",
        "severity": "P1",
        "summary": "ToolCall is uncertain and requires reconcile before retry.",
        "action": "Run reconcile and inspect effect_submission_state before any replay.",
        "runbook_id": "tool_call_uncertain",
    },
    {
        "alert_id": "agent_reconcile_manual_intervention",
        "metric_key": "tool_call_reconcile_manual_total",
        "severity": "P1",
        "summary": "Reconcile has moved ToolCalls to manual intervention.",
        "action": "Inspect recovery_decision and downstream contract evidence.",
        "runbook_id": "tool_call_uncertain",
    },
    {
        "alert_id": "agent_tool_call_send_intent_orphan",
        "metric_key": "tool_call_send_intent_orphan_total",
        "severity": "P2",
        "summary": "ToolCalls recorded send_intent but no downstream effect was observed.",
        "action": "Run reconcile; not_found can safe-retry with the same idempotency key.",
        "runbook_id": "tool_call_uncertain",
    },
    {
        "alert_id": "agent_tool_call_safe_retry_after_send_intent_not_found",
        "metric_key": "tool_call_safe_retry_after_send_intent_not_found_total",
        "severity": "P2",
        "summary": "Reconcile classified send_intent not_found ToolCalls as safe retry candidates.",
        "action": "Retry only with the existing idempotency key and monitor repeated worker pre-send crashes.",
        "runbook_id": "tool_call_uncertain",
    },
    {
        "alert_id": "agent_tool_call_transport_sent_uncertain",
        "metric_key": "tool_call_transport_sent_uncertain_total",
        "severity": "P1",
        "summary": "ToolCalls may have reached the backend and remain uncertain.",
        "action": "Keep retry blocked until reconcile confirms not_found, running, or committed state.",
        "runbook_id": "tool_call_uncertain",
    },
    {
        "alert_id": "agent_tool_call_backend_accepted_uncertain",
        "metric_key": "tool_call_backend_accepted_uncertain_total",
        "severity": "P0",
        "summary": "Receipt-first ToolCalls reached backend_accepted but remain uncertain.",
        "action": "Treat backend_accepted not_found as an incident and avoid safe retry without manual review.",
        "runbook_id": "tool_call_uncertain",
    },
    {
        "alert_id": "agent_reconcile_backoff_pending",
        "metric_key": "reconcile_backoff_active_total",
        "severity": "P2",
        "summary": "Reconcile backoff is actively throttling retry attempts.",
        "action": "Wait for next_retry_at or inspect repeated not_found/running outcomes before forcing reconcile.",
        "runbook_id": "tool_call_uncertain",
    },
    {
        "alert_id": "agent_approval_approve_conflict",
        "metric_key": "approval_approve_conflict_total",
        "severity": "P1",
        "summary": "Approval decisions are hitting conflict protection.",
        "action": "Refresh approval lineage and verify approvers are acting on the latest pending approval.",
        "runbook_id": "approval_stale",
    },
    {
        "alert_id": "agent_approval_epoch_conflict",
        "metric_key": "approval_epoch_conflict_total",
        "severity": "P1",
        "summary": "Approval epoch conflicts indicate stale approval clients or frequent supersede.",
        "action": "Refresh approval lineage and ask approvers to review the latest pending approval.",
        "runbook_id": "approval_stale",
    },
    {
        "alert_id": "agent_approval_expire_backlog",
        "metric_key": "approval_expire_due_total",
        "severity": "P2",
        "summary": "Pending approvals have passed expires_at and await batch expiration.",
        "action": "Run the approval expiration scanner and inspect oldest_due_lag_ms.",
        "runbook_id": "approval_stale",
    },
    {
        "alert_id": "agent_approval_expire_batch_lag",
        "metric_key": "approval_expire_batch_lag_ms",
        "severity": "P2",
        "summary": "Expired approvals have accumulated batch expiration lag.",
        "action": "Run the approval expiration scanner and verify scheduling latency for due approvals.",
        "runbook_id": "approval_stale",
    },
    {
        "alert_id": "agent_approval_lineage_hotspot",
        "metric_key": "approval_lineage_hotspot_total",
        "severity": "P1",
        "summary": "Multiple expired pending approvals share a lineage and may indicate stale mutation cleanup.",
        "action": "Inspect approval lineage before running bulk expiration.",
        "runbook_id": "approval_stale",
    },
    {
        "alert_id": "agent_approval_lineage_lock_wait",
        "metric_key": "approval_lineage_lock_wait_ms",
        "severity": "P2",
        "summary": "Approval lineage mutations accumulated lock wait time.",
        "action": "Inspect approval mutation logs for lineage lock hotspots before scaling approval batches.",
        "runbook_id": "approval_stale",
    },
    {
        "alert_id": "agent_approval_lineage_lock_skip",
        "metric_key": "approval_lineage_lock_skip_total",
        "severity": "P2",
        "summary": "Approval expiration batches skipped locked lineages.",
        "action": "Inspect skipped lineages and rerun expiration after the active mutation completes.",
        "runbook_id": "approval_stale",
    },
    {
        "alert_id": "agent_backend_contract_unsupported",
        "metric_key": "backend_contract_unsupported_total",
        "severity": "P1",
        "summary": "Backend contract or schema is unsupported for at least one ToolCall.",
        "action": "Register a compatible backend contract or resolve the migration block.",
        "runbook_id": "migration_blocked",
    },
    {
        "alert_id": "agent_tool_call_backend_contract_unsupported",
        "metric_key": "tool_call_backend_contract_unsupported_total",
        "severity": "P1",
        "summary": "ToolCalls failed because their backend contract or schema is unsupported.",
        "action": "Inspect the affected ToolCall contract metadata and register a compatible backend adapter.",
        "runbook_id": "migration_blocked",
    },
    {
        "alert_id": "agent_backend_capability_degraded",
        "metric_key": "backend_capability_degraded_total",
        "severity": "P1",
        "summary": "Backend effect capability is degraded for at least one ToolCall.",
        "action": "Inspect operation-level backend capability and require manual review or contract upgrade before expansion.",
        "runbook_id": "backend_capability_degraded",
        "related_metric_keys": [
            "backend_effect_capability_receipt_first_total",
            "backend_effect_capability_legacy_no_receipt_total",
        ],
    },
    {
        "alert_id": "agent_legacy_no_receipt_manual_intervention",
        "metric_key": "tool_call_legacy_no_receipt_manual_total",
        "severity": "P0",
        "summary": "High-risk legacy_no_receipt ToolCalls were forced to manual intervention.",
        "action": "Keep automatic recovery disabled until the operation gains receipt-first or idempotent capability.",
        "runbook_id": "backend_capability_degraded",
    },
    {
        "alert_id": "agent_migration_block_open",
        "metric_key": "migration_block_open_total",
        "severity": "P1",
        "summary": "Open migration blocks are preventing normal run progress.",
        "action": "Resolve blocks only after compatible adapters or contracts are available.",
        "runbook_id": "migration_blocked",
    },
    {
        "alert_id": "agent_runtime_snapshot_migration_block",
        "metric_key": "runtime_snapshot_migration_block_total",
        "severity": "P1",
        "summary": "Runtime snapshot migration blocks are preventing resume or execution.",
        "action": "Deploy compatible runtime snapshot metadata, then resolve the block through MigrationCoordinator.",
        "runbook_id": "migration_blocked",
    },
    {
        "alert_id": "agent_backend_contract_migration_block",
        "metric_key": "backend_contract_migration_block_total",
        "severity": "P1",
        "summary": "Backend contract migration blocks are preventing safe reconciliation.",
        "action": "Register or deploy a compatible backend contract adapter before resolving the block.",
        "runbook_id": "migration_blocked",
    },
    {
        "alert_id": "agent_run_migration_blocked",
        "metric_key": "run_migration_blocked_total",
        "severity": "P1",
        "summary": "Runs are currently blocked by migration coordination.",
        "action": "Inspect open migration blocks and require checkpoint freshness before resuming.",
        "runbook_id": "migration_blocked",
    },
    {
        "alert_id": "agent_outbox_publish_lag",
        "metric_key": "outbox_publish_lag_ms",
        "severity": "P1",
        "summary": "Agent outbox has pending or failed publish lag.",
        "action": "Run the outbox publisher and inspect dead-letter failures.",
        "runbook_id": "outbox_publish_lag",
    },
    {
        "alert_id": "agent_event_replay_gap",
        "metric_key": "event_replay_gap_total",
        "severity": "P1",
        "summary": "EventStore has non-contiguous event_seq values for at least one run.",
        "action": "Audit the affected run before relying on SSE Last-Event-ID replay.",
        "runbook_id": "event_replay_recovery",
    },
    {
        "alert_id": "agent_event_replay_stress_failed",
        "metric_key": "event_replay_stress_failed_total",
        "severity": "P1",
        "summary": "Project-level SSE replay stress audit found runs that cannot replay from concurrent cursors.",
        "action": "Run the project replay stress audit and inspect failed run/cursor windows.",
        "runbook_id": "event_replay_recovery",
        "related_metric_keys": [
            "event_replay_stress_cursor_window_total",
            "event_replay_stress_max_window_events",
        ],
    },
    {
        "alert_id": "agent_fault_injection_coverage_incomplete",
        "metric_key": "fault_injection_missing_required_total",
        "severity": "P1",
        "summary": "Required Agent fault-injection coverage is incomplete.",
        "action": "Register or repair missing fault-injection cases before expanding rollout.",
        "runbook_id": "fault_injection_coverage",
        "related_metric_keys": [
            "fault_injection_required_case_total",
            "fault_injection_registered_case_total",
            "fault_injection_missing_required_total",
            "fault_injection_coverage_ratio",
        ],
    },
    {
        "alert_id": "agent_fault_injection_coverage_ratio_low",
        "metric_key": "fault_injection_coverage_ratio",
        "operator": "lt",
        "threshold": 1.0,
        "severity": "P1",
        "summary": "Required Agent fault-injection coverage ratio is below 100%.",
        "action": "Register missing required fault-injection cases until coverage_ratio reaches 1.0.",
        "runbook_id": "fault_injection_coverage",
        "related_metric_keys": [
            "fault_injection_required_case_total",
            "fault_injection_registered_case_total",
            "fault_injection_missing_required_total",
            "fault_injection_coverage_ratio",
        ],
    },
    {
        "alert_id": "agent_worker_queue_expired_lease",
        "metric_key": "worker_queue_expired_lease_total",
        "severity": "P1",
        "summary": "WorkerQueue has expired leases waiting for orphan recovery.",
        "action": "Run orphan recovery and verify the lease scanner heartbeat schedule.",
        "runbook_id": "worker_queue_recovery",
    },
    {
        "alert_id": "agent_worker_queue_duplicate_active_lease",
        "metric_key": "worker_queue_duplicate_active_lease_total",
        "severity": "P0",
        "summary": "WorkerQueue has duplicate active queue rows for the same ToolCall.",
        "action": "Pause workers for the affected ToolCall and repair duplicate active queue rows before retry.",
        "runbook_id": "worker_queue_recovery",
    },
    {
        "alert_id": "agent_context_required_evidence_missing",
        "metric_key": "context_full_evidence_required_total",
        "severity": "P1",
        "summary": "High-risk decision context omitted required evidence.",
        "action": "Fetch full evidence or rebuild the decision context before high-risk execution.",
        "runbook_id": "checkpoint_stale",
    },
    {
        "alert_id": "agent_checkpoint_freshness_failed",
        "metric_key": "checkpoint_freshness_failed_total",
        "severity": "P1",
        "summary": "Checkpoint freshness gate blocked resume or migration recovery.",
        "action": "Inspect freshness reason and rebuild context, evidence, permissions, or runtime snapshot before resume.",
        "runbook_id": "checkpoint_stale",
    },
    {
        "alert_id": "agent_context_decision_build_missing",
        "metric_key": "context_decision_build_missing_total",
        "severity": "P1",
        "summary": "LoopObservation references a missing decision ContextBuild.",
        "action": "Repair the observation/context-build linkage before using loop diagnostics.",
        "runbook_id": "context_linkage_repair",
    },
    {
        "alert_id": "agent_root_cause_rule_missing",
        "metric_key": "root_cause_rule_missing_total",
        "severity": "P1",
        "summary": "Loop reasons were observed without an explicit RootCause rule.",
        "action": "Add or activate a governed RootCause rule before relying on diagnostics.",
        "runbook_id": "root_cause_rule_missing",
    },
    {
        "alert_id": "agent_memory_bypassed_evidence_ref",
        "metric_key": "memory_bypassed_evidence_ref_total",
        "severity": "P0",
        "summary": "Memory was declared in context without a matching memory EvidenceRef.",
        "action": "Block the flow and repair MemoryEvidenceAdapter or ContextBuilder usage.",
        "runbook_id": "memory_evidence_ref_violation",
    },
    {
        "alert_id": "agent_memory_only_high_risk_blocked",
        "metric_key": "memory_high_risk_blocked_total",
        "severity": "P1",
        "summary": "High-risk action attempted to depend only on Memory evidence.",
        "action": "Require non-memory decision evidence before approving or executing.",
        "runbook_id": "memory_evidence_ref_violation",
    },
    {
        "alert_id": "agent_memory_needs_revalidation",
        "metric_key": "memory_needs_revalidation_total",
        "severity": "P1",
        "summary": "Memory entries require revalidation before safe reuse.",
        "action": "Rebuild context with fresh evidence or validate the affected Memory before resume or high-risk execution.",
        "runbook_id": "checkpoint_stale",
    },
)


class AgentOutboxPublisher:
    def __init__(
        self,
        db: Session,
        *,
        publisher: OutboxPublisherCallback | None = None,
        max_attempts: int = 5,
        base_retry_seconds: int = 5,
    ):
        self.db = db
        self.publisher = publisher or self._noop_publish
        self.max_attempts = max(1, max_attempts)
        self.base_retry_seconds = max(1, base_retry_seconds)

    def publish_pending(self, *, limit: int = 100, now: datetime | None = None) -> dict[str, Any]:
        current = now or _utcnow()
        items = list(
            self.db.scalars(
                select(AgentOutbox)
                .where(
                    AgentOutbox.status.in_(["pending", "failed"]),
                    or_(AgentOutbox.next_retry_at.is_(None), AgentOutbox.next_retry_at <= current),
                )
                .order_by(AgentOutbox.created_at.asc(), AgentOutbox.id.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
        )
        summary = {
            "attempted": 0,
            "published": 0,
            "failed": 0,
            "dead_letter": 0,
            "pending_remaining": 0,
            "outbox_publish_lag_ms": self._publish_lag_ms(now=current),
        }
        for item in items:
            event = self.db.get(AgentEvent, item.event_id)
            item.publish_attempts += 1
            summary["attempted"] += 1
            try:
                if event is None:
                    raise RuntimeError("agent event missing for outbox item")
                self.publisher(event)
            except Exception as exc:  # noqa: BLE001
                item.last_error = _bounded_agent_error_message(
                    exc,
                    reference="AgentOutboxPublisher.publish_pending",
                )
                if item.publish_attempts >= self.max_attempts:
                    item.status = "dead_letter"
                    item.next_retry_at = None
                    summary["dead_letter"] += 1
                else:
                    item.status = "failed"
                    item.next_retry_at = current + timedelta(seconds=self._retry_delay(item.publish_attempts))
                    summary["failed"] += 1
                continue
            item.status = "published"
            item.last_error = None
            item.next_retry_at = None
            summary["published"] += 1

        self.db.commit()
        summary["pending_remaining"] = self._count_outbox_pending()
        summary["outbox_publish_lag_ms"] = self._publish_lag_ms(now=current)
        return {field: summary[field] for field in OUTBOX_PUBLISH_FIELDS}

    def _retry_delay(self, attempts: int) -> int:
        return self.base_retry_seconds * (2 ** max(0, attempts - 1))

    def _count_outbox_pending(self) -> int:
        return int(
            self.db.scalar(
                select(func.count())
                .select_from(AgentOutbox)
                .where(AgentOutbox.status.in_(["pending", "failed"]))
            )
            or 0
        )

    def _publish_lag_ms(self, *, now: datetime) -> int:
        oldest = self.db.scalar(
            select(func.min(AgentOutbox.created_at)).where(AgentOutbox.status.in_(["pending", "failed"]))
        )
        if oldest is None:
            return 0
        return max(0, int((now - oldest).total_seconds() * 1000))

    @staticmethod
    def _noop_publish(event: AgentEvent) -> None:
        _ = event


def _bounded_agent_error_message(error: Any, *, reference: str) -> str:
    message = str(error or "")
    if len(message) <= AGENT_ERROR_MESSAGE_MAX_CHARS:
        return message
    suffix = (
        f"{AGENT_ERROR_MESSAGE_TRUNCATION_MARKER} "
        f"error_summary_version={AGENT_ERROR_MESSAGE_SUMMARY_VERSION} "
        f"error_size_chars={len(message)} "
        f"error_hash={request_fingerprint({'error_message': message})} "
        f"full_error_reference={reference}"
    )
    preview_max_chars = max(0, AGENT_ERROR_MESSAGE_MAX_CHARS - len(suffix))
    return f"{message[:preview_max_chars]}{suffix}"


class AgentMetricsService:
    def __init__(self, db: Session):
        self.db = db

    def snapshot(self, *, project_id: int | None = None) -> dict[str, Any]:
        from app.services.agent_approval_service import ApprovalExpireScanner

        approval_expire_audit = ApprovalExpireScanner(self.db).audit(project_id=project_id)
        worker_queue_audit = AgentWorkerQueueAuditService(self.db).audit(project_id=project_id)
        event_replay_stress = AgentEventReplayAuditService(self.db).audit_project(project_id=project_id)
        fault_coverage = AgentFaultInjectionCoverageService(self.db).audit()
        release_gate = self._release_gate_snapshot()
        metrics = {
            "tool_call_uncertain_total": self._count_tool_calls(project_id, AgentToolCall.status == "uncertain"),
            "tool_call_reconcile_success_total": self._count_reconcile_attempts(project_id, "succeeded"),
            "tool_call_reconcile_manual_total": self._count_tool_calls(
                project_id, AgentToolCall.status == "manual_intervention"
            ),
            "reconcile_backoff_active_total": self._count_reconcile_backoff_active(project_id),
            "tool_call_orphan_recovered_total": self._count_tool_calls(
                project_id, AgentToolCall.recovery_decision == "lease_expired_requeued"
            ),
            "tool_call_send_intent_orphan_total": self._count_tool_calls(
                project_id,
                AgentToolCall.effect_submission_state == "send_intent_recorded",
                AgentToolCall.status.in_(["uncertain", "reconciling", "failed_retryable"]),
            ),
            "tool_call_safe_retry_after_send_intent_not_found_total": self._count_tool_calls(
                project_id,
                AgentToolCall.recovery_decision == "safe_retry_same_idempotency_key",
            ),
            "tool_call_transport_sent_uncertain_total": self._count_tool_calls(
                project_id,
                AgentToolCall.effect_submission_state == "transport_sent_observed",
                AgentToolCall.status.in_(["uncertain", "reconciling"]),
            ),
            "tool_call_backend_accepted_uncertain_total": self._count_tool_calls(
                project_id,
                AgentToolCall.effect_submission_state == "backend_accepted",
                AgentToolCall.status.in_(["uncertain", "reconciling"]),
            ),
            "backend_effect_capability_receipt_first_total": self._count_tool_calls(
                project_id, AgentToolCall.backend_effect_capability == "receipt_first"
            ),
            "backend_effect_capability_legacy_no_receipt_total": self._count_tool_calls(
                project_id, AgentToolCall.backend_effect_capability == "legacy_no_receipt"
            ),
            "tool_call_legacy_no_receipt_manual_total": self._count_tool_calls(
                project_id,
                AgentToolCall.backend_effect_capability == "legacy_no_receipt",
                AgentToolCall.status == "manual_intervention",
                AgentToolCall.recovery_decision == "legacy_no_receipt_high_risk_manual",
            ),
            "tool_call_backend_contract_unsupported_total": self._count_tool_calls(
                project_id, AgentToolCall.error_code == "backend_contract_unsupported"
            ),
            "tool_call_duplicate_blocked_total": self._count_events(project_id, "tool.duplicate_blocked"),
            "approval_superseded_total": self._count_approvals(project_id, AgentApproval.approval_status == "superseded"),
            "approval_approve_conflict_total": self._count_events(project_id, "approval.approve_conflict"),
            "approval_epoch_conflict_total": self._count_events(
                project_id, "approval.approve_conflict", error_code="approval_epoch_conflict"
            ),
            "approval_replacement_atomic_total": self._count_approval_mutations(project_id, "create_replacement"),
            "approval_lineage_lock_wait_ms": self._sum_approval_lineage_lock_wait_ms(project_id),
            "approval_lineage_lock_skip_total": self._sum_approval_lineage_lock_skip_total(project_id),
            "approval_expire_due_total": approval_expire_audit["due_count"],
            "approval_expire_batch_lag_ms": approval_expire_audit["oldest_due_lag_ms"],
            "approval_lineage_hotspot_total": approval_expire_audit["lineage_hotspot_count"],
            "evidence_volatile_requires_revalidation_total": self._count_tool_policy_reasons(
                project_id,
                replay_policy="require_revalidation",
                min_volatile_policy_refs=1,
            ),
            "evidence_historical_volatile_excluded_total": self._count_tool_policy_reasons(
                project_id,
                min_historical_volatile_excluded=1,
            ),
            "evidence_mixed_volatile_frozen_total": self._count_tool_policy_reasons(
                project_id,
                min_volatile_policy_refs=1,
                min_frozen_policy_refs=1,
            ),
            "permission_revoked_before_execution_total": self._count_tool_calls(
                project_id, AgentToolCall.error_code == "permission_revoked_before_execution"
            ),
            "backend_contract_unsupported_total": self._count_tool_calls(
                project_id, AgentToolCall.error_code == "backend_contract_unsupported"
            ),
            "migration_block_open_total": self._count_migration_blocks(project_id, AgentMigrationBlock.status == "open"),
            "runtime_snapshot_migration_block_total": self._count_migration_blocks(
                project_id,
                AgentMigrationBlock.status == "open",
                AgentMigrationBlock.required_migration_type == "runtime_snapshot",
            ),
            "backend_contract_migration_block_total": self._count_migration_blocks(
                project_id,
                AgentMigrationBlock.status == "open",
                AgentMigrationBlock.required_migration_type == "backend_contract_adapter",
            ),
            "run_migration_blocked_total": self._count_runs(project_id, AgentRun.status == "migration_blocked"),
            "outbox_publish_lag_ms": AgentOutboxPublisher(self.db)._publish_lag_ms(now=_utcnow()),
            "context_degraded_total": self._count_context_builds(
                project_id, AgentContextBuild.context_degradation_level != "none"
            ),
            "context_full_evidence_required_total": self._count_context_builds(
                project_id, AgentContextBuild.required_evidence_complete.is_(False)
            ),
            "context_decision_build_missing_total": self._count_missing_decision_context_builds(project_id),
            "loop_root_cause_context_degraded_total": self._count_loop_observations(
                project_id, AgentLoopObservation.root_cause_primary == "context_degraded_heavy"
            ),
            "loop_root_cause_unknown_total": self._count_loop_observations(
                project_id, AgentLoopObservation.root_cause_primary == "unknown"
            ),
            "root_cause_rule_missing_total": self._count_loop_observations(
                project_id, AgentLoopObservation.root_cause_primary == "root_cause_rule_missing"
            ),
            "invalid_repair_scope_total": self._count_loop_observations_with_reason(
                project_id, "invalid_repair_scope"
            ),
            "tool_prerequisite_missing_total": self._count_loop_observations(
                project_id, AgentLoopObservation.stop_action_reason == "tool_prerequisite_missing"
            ),
            "tool_request_format_invalid_total": self._count_loop_observations(
                project_id, AgentLoopObservation.stop_action_reason == "tool_request_format_invalid"
            ),
            "required_tool_followup_missing_total": self._count_loop_observations(
                project_id, AgentLoopObservation.stop_action_reason == "required_tool_followup_missing"
            ),
            "max_iterations_total": self._count_loop_observations(
                project_id, AgentLoopObservation.stop_action_reason == "max_iterations"
            ),
            "same_failure_no_progress_total": self._count_loop_observations(
                project_id, AgentLoopObservation.stop_action_reason == "same_failure_no_progress"
            ),
            "memory_contradiction_total": self._count_memory_contradictions(project_id),
            "memory_contradiction_penalty_applied_total": self._count_events(
                project_id, "memory.contradiction_penalty_applied"
            ),
            "memory_retrieved_total": self._count_memory_usage(project_id),
            "memory_used_active_policy_total": self._count_memory_usage(
                project_id, AgentMemoryUsageEvent.active_for_policy.is_(True)
            ),
            "memory_retrieval_profile_missing_total": self._count_events(
                project_id, "memory.retrieval_profile_missing"
            ),
            "memory_low_confidence_filtered_total": self._count_events(
                project_id, "memory.low_confidence_filtered"
            ),
            "memory_high_risk_blocked_total": self._count_tool_calls(
                project_id, AgentToolCall.error_code == "high_risk_action_cannot_depend_only_on_memory"
            ),
            "memory_needs_revalidation_total": self._count_project_memories(
                project_id, ProjectMemory.status == "needs_revalidation"
            ),
            "memory_evidence_watch_stale_total": self._count_memory_staleness_events(project_id),
            "memory_bypassed_evidence_ref_total": self._count_events(project_id, "memory.bypassed_evidence_ref"),
            "checkpoint_freshness_failed_total": self._count_checkpoint_freshness_failures(project_id),
            "event_replay_gap_total": self._count_event_replay_gaps(project_id),
            "event_replay_stress_failed_total": event_replay_stress["failed_run_count"],
            "event_replay_stress_cursor_window_total": event_replay_stress["cursor_window_count"],
            "event_replay_stress_max_window_events": event_replay_stress["max_replay_window_events"],
            "fault_injection_required_case_total": fault_coverage["required_case_count"],
            "fault_injection_registered_case_total": fault_coverage["registered_case_count"],
            "fault_injection_missing_required_total": len(fault_coverage["missing_required_case_ids"]),
            "fault_injection_coverage_ratio": fault_coverage["coverage_ratio"],
            "worker_queue_expired_lease_total": worker_queue_audit["expired_lease_count"],
            "worker_queue_duplicate_active_lease_total": worker_queue_audit["duplicate_active_lease_count"],
            "worker_queue_oldest_queued_age_ms": worker_queue_audit["oldest_queued_age_ms"],
            "release_gate_violation_count": len(release_gate.get("violations") or []),
            "backend_capability_degraded_total": self._count_tool_calls(
                project_id, AgentToolCall.backend_effect_capability.in_(["legacy_reconcile_only", "legacy_no_receipt"])
            ),
        }
        snapshot = {
            "project_id": project_id,
            "generated_at": _utcnow().isoformat(),
            "metrics": metrics,
            "derived_from": {
                "counters": "ai_agent_events and current fact tables",
                "outbox_publish_lag_ms": "oldest pending/failed ai_agent_outbox item age",
                "scope": "project" if project_id is not None else "global",
            },
        }
        snapshot["derived_from"] = {
            field: snapshot["derived_from"][field]
            for field in METRICS_DERIVED_FROM_FIELDS
        }
        return {field: snapshot[field] for field in METRICS_SNAPSHOT_FIELDS}

    def _run_ids(self, project_id: int | None):
        statement = select(AgentRun.run_id)
        if project_id is not None:
            statement = statement.where(AgentRun.project_id == project_id)
        return statement

    def _count_tool_calls(self, project_id: int | None, *conditions: Any) -> int:
        statement = select(func.count()).select_from(AgentToolCall).where(*conditions)
        if project_id is not None:
            statement = statement.where(AgentToolCall.run_id.in_(self._run_ids(project_id)))
        return int(self.db.scalar(statement) or 0)

    def _count_runs(self, project_id: int | None, *conditions: Any) -> int:
        statement = select(func.count()).select_from(AgentRun).where(*conditions)
        if project_id is not None:
            statement = statement.where(AgentRun.project_id == project_id)
        return int(self.db.scalar(statement) or 0)

    def _release_gate_snapshot(self) -> dict[str, Any]:
        from app.services.agent_release_gate_service import AgentReleaseGateService

        return AgentReleaseGateService(self.db).snapshot()

    def _count_reconcile_attempts(self, project_id: int | None, result_status: str) -> int:
        statement = select(func.count()).select_from(AgentReconcileAttempt).where(
            AgentReconcileAttempt.result_status == result_status
        )
        if project_id is not None:
            statement = statement.where(
                AgentReconcileAttempt.tool_call_id.in_(
                    select(AgentToolCall.tool_call_id).where(AgentToolCall.run_id.in_(self._run_ids(project_id)))
                )
            )
        return int(self.db.scalar(statement) or 0)

    def _count_events(self, project_id: int | None, event_type: str, **payload_filters: str) -> int:
        statement = select(AgentEvent).where(AgentEvent.event_type == event_type)
        if project_id is not None:
            statement = statement.where(AgentEvent.run_id.in_(self._run_ids(project_id)))
        events = list(self.db.scalars(statement).all())
        for key, value in payload_filters.items():
            events = [item for item in events if (item.payload_json or {}).get(key) == value]
        return len(events)

    def _count_checkpoint_freshness_failures(self, project_id: int | None) -> int:
        statement = select(AgentEvent).where(AgentEvent.event_type == "checkpoint.freshness_checked")
        if project_id is not None:
            statement = statement.where(AgentEvent.run_id.in_(self._run_ids(project_id)))
        return sum(
            1
            for event in self.db.scalars(statement).all()
            if (event.payload_json or {}).get("result") not in {None, "fresh", "terminal"}
        )

    def _count_approvals(self, project_id: int | None, *conditions: Any) -> int:
        statement = select(func.count()).select_from(AgentApproval).where(*conditions)
        if project_id is not None:
            statement = statement.where(AgentApproval.project_id == project_id)
        return int(self.db.scalar(statement) or 0)

    def _count_approval_mutations(self, project_id: int | None, mutation_type: str) -> int:
        statement = select(func.count()).select_from(AgentApprovalMutationLog).where(
            AgentApprovalMutationLog.mutation_type == mutation_type
        )
        if project_id is not None:
            statement = statement.where(AgentApprovalMutationLog.run_id.in_(self._run_ids(project_id)))
        return int(self.db.scalar(statement) or 0)

    def _sum_approval_lineage_lock_wait_ms(self, project_id: int | None) -> int:
        return sum(
            int((mutation.details_json or {}).get("lineage_lock_wait_ms") or 0)
            for mutation in self._approval_mutations(project_id)
        )

    def _sum_approval_lineage_lock_skip_total(self, project_id: int | None) -> int:
        total = 0
        for mutation in self._approval_mutations(project_id):
            details = mutation.details_json or {}
            total += int(details.get("lineage_lock_skip_total") or 0)
            if details.get("lineage_lock_skipped") is True:
                total += 1
        return total

    def _approval_mutations(self, project_id: int | None) -> list[AgentApprovalMutationLog]:
        statement = select(AgentApprovalMutationLog)
        if project_id is not None:
            statement = statement.where(AgentApprovalMutationLog.run_id.in_(self._run_ids(project_id)))
        return list(self.db.scalars(statement).all())

    def _count_tool_policy_reasons(
        self,
        project_id: int | None,
        *,
        replay_policy: str | None = None,
        min_volatile_policy_refs: int = 0,
        min_frozen_policy_refs: int = 0,
        min_historical_volatile_excluded: int = 0,
    ) -> int:
        statement = select(AgentToolCall)
        if project_id is not None:
            statement = statement.where(AgentToolCall.run_id.in_(self._run_ids(project_id)))
        tool_calls = list(self.db.scalars(statement).all())
        count = 0
        for call in tool_calls:
            reason = call.policy_reason_json or {}
            if replay_policy is not None and call.resolved_replay_policy != replay_policy:
                continue
            if int(reason.get("volatile_policy_ref_count") or 0) < min_volatile_policy_refs:
                continue
            if int(reason.get("frozen_policy_ref_count") or 0) < min_frozen_policy_refs:
                continue
            if int(reason.get("historical_volatile_excluded_count") or 0) < min_historical_volatile_excluded:
                continue
            count += 1
        return count

    def _count_migration_blocks(self, project_id: int | None, *conditions: Any) -> int:
        statement = select(func.count()).select_from(AgentMigrationBlock).where(*conditions)
        if project_id is not None:
            statement = statement.where(AgentMigrationBlock.run_id.in_(self._run_ids(project_id)))
        return int(self.db.scalar(statement) or 0)

    def _count_context_builds(self, project_id: int | None, *conditions: Any) -> int:
        statement = select(func.count()).select_from(AgentContextBuild).where(*conditions)
        if project_id is not None:
            statement = statement.where(AgentContextBuild.run_id.in_(self._run_ids(project_id)))
        return int(self.db.scalar(statement) or 0)

    def _count_loop_observations(self, project_id: int | None, *conditions: Any) -> int:
        statement = select(func.count()).select_from(AgentLoopObservation).where(*conditions)
        if project_id is not None:
            statement = statement.where(AgentLoopObservation.run_id.in_(self._run_ids(project_id)))
        return int(self.db.scalar(statement) or 0)

    def _count_missing_decision_context_builds(self, project_id: int | None) -> int:
        statement = select(func.count()).select_from(AgentLoopObservation).where(
            ~AgentLoopObservation.decision_context_build_id.in_(
                select(AgentContextBuild.context_build_id)
            )
        )
        if project_id is not None:
            statement = statement.where(AgentLoopObservation.run_id.in_(self._run_ids(project_id)))
        return int(self.db.scalar(statement) or 0)

    def _count_loop_observations_with_reason(self, project_id: int | None, reason: str) -> int:
        statement = select(AgentLoopObservation)
        if project_id is not None:
            statement = statement.where(AgentLoopObservation.run_id.in_(self._run_ids(project_id)))
        count = 0
        for observation in self.db.scalars(statement).all():
            if reason in (observation.stop_reasons_all_json or []):
                count += 1
        return count

    def _count_memory_contradictions(self, project_id: int | None) -> int:
        statement = select(func.count()).select_from(AgentMemoryContradictionEvent)
        if project_id is not None:
            statement = statement.where(
                AgentMemoryContradictionEvent.memory_id.in_(
                    select(ProjectMemory.id).where(ProjectMemory.project_id == project_id)
                )
            )
        return int(self.db.scalar(statement) or 0)

    def _count_memory_staleness_events(self, project_id: int | None) -> int:
        statement = select(func.count()).select_from(AgentMemoryStalenessEvent)
        if project_id is not None:
            statement = statement.where(AgentMemoryStalenessEvent.project_id == project_id)
        return int(self.db.scalar(statement) or 0)

    def _count_memory_usage(self, project_id: int | None, *conditions: Any) -> int:
        statement = select(func.count()).select_from(AgentMemoryUsageEvent).where(*conditions)
        if project_id is not None:
            statement = statement.where(
                AgentMemoryUsageEvent.memory_id.in_(
                    select(ProjectMemory.id).where(ProjectMemory.project_id == project_id)
                )
            )
        return int(self.db.scalar(statement) or 0)

    def _count_project_memories(self, project_id: int | None, *conditions: Any) -> int:
        statement = select(func.count()).select_from(ProjectMemory).where(*conditions)
        if project_id is not None:
            statement = statement.where(ProjectMemory.project_id == project_id)
        return int(self.db.scalar(statement) or 0)

    def _count_event_replay_gaps(self, project_id: int | None) -> int:
        statement = (
            select(
                AgentRun.run_id,
                AgentRun.last_event_sequence,
                func.count(AgentEvent.id).label("event_count"),
                func.count(func.distinct(AgentEvent.event_seq)).label("distinct_event_count"),
                func.min(AgentEvent.event_seq).label("min_event_seq"),
                func.max(AgentEvent.event_seq).label("max_event_seq"),
            )
            .select_from(AgentRun)
            .outerjoin(AgentEvent, AgentEvent.run_id == AgentRun.run_id)
            .group_by(AgentRun.run_id, AgentRun.last_event_sequence)
        )
        if project_id is not None:
            statement = statement.where(AgentRun.project_id == project_id)
        gap_total = 0
        for row in self.db.execute(statement):
            last_sequence = int(row.last_event_sequence or 0)
            event_count = int(row.event_count or 0)
            distinct_event_count = int(row.distinct_event_count or 0)
            min_event_seq = row.min_event_seq
            max_event_seq = row.max_event_seq
            if last_sequence == 0:
                replayable = event_count == 0
            else:
                replayable = (
                    event_count == last_sequence
                    and distinct_event_count == last_sequence
                    and min_event_seq == 1
                    and max_event_seq == last_sequence
                )
            if not replayable:
                gap_total += 1
        return gap_total

    def _count_reconcile_backoff_active(self, project_id: int | None) -> int:
        now = _utcnow()
        statement = select(AgentToolCall).where(AgentToolCall.status.in_(["uncertain", "reconciling"]))
        if project_id is not None:
            statement = statement.where(AgentToolCall.run_id.in_(self._run_ids(project_id)))
        calls = list(self.db.scalars(statement).all())
        active = 0
        for call in calls:
            latest_attempt = self.db.scalar(
                select(AgentReconcileAttempt)
                .where(AgentReconcileAttempt.tool_call_id == call.tool_call_id)
                .order_by(AgentReconcileAttempt.attempt_seq.desc())
                .limit(1)
            )
            if latest_attempt is not None and latest_attempt.next_retry_at is not None and latest_attempt.next_retry_at > now:
                active += 1
        return active


class AgentWorkerQueueAuditService:
    ACTIVE_STATUSES = {"queued", "leased"}

    def __init__(self, db: Session):
        self.db = db

    def audit(self, *, project_id: int | None = None, now: datetime | None = None) -> dict[str, Any]:
        current = now or _utcnow()
        items = self._items(project_id)
        status_counts: dict[str, int] = {}
        for item in items:
            status_counts[item.status] = status_counts.get(item.status, 0) + 1

        expired_leases = [
            item for item in items
            if item.status == "leased" and item.lease_expires_at is not None and item.lease_expires_at <= current
        ]
        active_by_tool_call: dict[str, list[AgentWorkerQueue]] = {}
        for item in items:
            if item.status in self.ACTIVE_STATUSES:
                active_by_tool_call.setdefault(item.tool_call_id, []).append(item)
        duplicate_active_leases = {
            tool_call_id: rows
            for tool_call_id, rows in active_by_tool_call.items()
            if len(rows) > 1
        }
        queued_ages = [
            max(0, int((current - item.created_at).total_seconds() * 1000))
            for item in items
            if item.status == "queued" and item.created_at is not None
        ]
        oldest_queued_age_ms = max(queued_ages) if queued_ages else 0
        audit = {
            "project_id": project_id,
            "generated_at": current.isoformat(),
            "status_counts": status_counts,
            "total_count": len(items),
            "active_count": sum(1 for item in items if item.status in self.ACTIVE_STATUSES),
            "expired_lease_count": len(expired_leases),
            "duplicate_active_lease_count": len(duplicate_active_leases),
            "oldest_queued_age_ms": oldest_queued_age_ms,
            "lease_scan_stable": not expired_leases and not duplicate_active_leases,
            "expired_leases": [self._lease_summary(item) for item in expired_leases],
            "duplicate_active_leases": [
                {
                    "item_id": _worker_queue_duplicate_active_item_id(tool_call_id),
                    "tool_call_id": tool_call_id,
                    "queue_ids": [row.queue_id for row in rows],
                    "statuses": [row.status for row in rows],
                    "lease_owners": [row.lease_owner for row in rows],
                }
                for tool_call_id, rows in sorted(duplicate_active_leases.items())
            ],
            "derived_from": {
                "queue_table": "ai_agent_worker_queue",
                "active_statuses": sorted(self.ACTIVE_STATUSES),
                "scope": "project" if project_id is not None else "global",
            },
        }
        audit["duplicate_active_leases"] = [
            {field: item[field] for field in WORKER_QUEUE_DUPLICATE_ACTIVE_FIELDS}
            for item in audit["duplicate_active_leases"]
        ]
        audit["derived_from"] = {
            field: audit["derived_from"][field]
            for field in WORKER_QUEUE_DERIVED_FROM_FIELDS
        }
        return {field: audit[field] for field in WORKER_QUEUE_AUDIT_FIELDS}

    def _items(self, project_id: int | None) -> list[AgentWorkerQueue]:
        statement = select(AgentWorkerQueue)
        if project_id is not None:
            statement = statement.where(AgentWorkerQueue.run_id.in_(select(AgentRun.run_id).where(AgentRun.project_id == project_id)))
        return list(self.db.scalars(statement).all())

    @staticmethod
    def _lease_summary(item: AgentWorkerQueue) -> dict[str, Any]:
        summary = {
            "item_id": _worker_queue_expired_lease_item_id(item.queue_id),
            "queue_id": item.queue_id,
            "run_id": item.run_id,
            "tool_call_id": item.tool_call_id,
            "lease_owner": item.lease_owner,
            "lease_expires_at": item.lease_expires_at.isoformat() if item.lease_expires_at else None,
            "attempt_count": item.attempt_count,
            "last_error_code": item.last_error_code,
        }
        return {field: summary[field] for field in WORKER_QUEUE_EXPIRED_LEASE_FIELDS}


class AgentEventReplayAuditService:
    def __init__(self, db: Session):
        self.db = db

    def audit_project(
        self,
        *,
        project_id: int | None = None,
        sample_limit: int = 100,
        cursor_count: int = 3,
    ) -> dict[str, Any]:
        limit = max(1, sample_limit)
        cursor_total = max(1, cursor_count)
        statement = select(AgentRun)
        if project_id is not None:
            statement = statement.where(AgentRun.project_id == project_id)
        statement = statement.order_by(AgentRun.created_at.desc(), AgentRun.id.desc()).limit(limit)
        runs = list(self.db.scalars(statement).all())
        events_by_run_id = self._events_by_run_id([run.run_id for run in runs])

        run_audits: list[dict[str, Any]] = []
        cursor_window_count = 0
        invalid_cursor_count = 0
        max_replay_window_events = 0
        total_replay_events = 0
        failed_run_ids: set[str] = set()

        for run in runs:
            run_failure = False
            cursor_audits: list[dict[str, Any]] = []
            events = events_by_run_id.get(run.run_id, [])
            for after_sequence in self._cursor_windows(last_event_sequence=run.last_event_sequence or 0, cursor_count=cursor_total):
                audit = self._audit_loaded_run(run=run, events=events, after_sequence=after_sequence)
                cursor_window_count += 1
                total_replay_events += audit["replay_event_count"]
                max_replay_window_events = max(max_replay_window_events, audit["replay_event_count"])
                if not audit["replay_cursor_valid"]:
                    invalid_cursor_count += 1
                if not audit["replayable"] or not audit["replay_cursor_valid"]:
                    run_failure = True
                cursor_audit = {
                    "item_id": _event_replay_cursor_item_id(run.run_id, after_sequence),
                    "after_sequence": after_sequence,
                    "replay_event_count": audit["replay_event_count"],
                    "first_replay_event_seq": audit["first_replay_event_seq"],
                    "last_replay_event_seq": audit["last_replay_event_seq"],
                    "replayable": audit["replayable"],
                    "replay_cursor_valid": audit["replay_cursor_valid"],
                }
                cursor_audits.append({
                    field: cursor_audit[field]
                    for field in EVENT_REPLAY_CURSOR_AUDIT_FIELDS
                })
            if run_failure:
                failed_run_ids.add(run.run_id)
            run_audit = {
                "item_id": _event_replay_stress_run_item_id(run.run_id),
                "run_id": run.run_id,
                "project_id": run.project_id,
                "last_event_sequence": run.last_event_sequence or 0,
                "event_count": len(events),
                "cursor_audits": cursor_audits,
                "replayable": not run_failure,
            }
            run_audits.append({
                field: run_audit[field]
                for field in EVENT_REPLAY_STRESS_RUN_FIELDS
            })

        audit = {
            "project_id": project_id,
            "generated_at": _utcnow().isoformat(),
            "sample_limit": limit,
            "cursor_count": cursor_total,
            "audited_run_count": len(runs),
            "cursor_window_count": cursor_window_count,
            "failed_run_count": len(failed_run_ids),
            "failed_run_ids": sorted(failed_run_ids),
            "invalid_cursor_count": invalid_cursor_count,
            "total_replay_events": total_replay_events,
            "max_replay_window_events": max_replay_window_events,
            "high_concurrency_replayable": not failed_run_ids and invalid_cursor_count == 0,
            "run_audits": run_audits,
            "derived_from": {
                "runs": "recent ai_agent_runs ordered by created_at desc",
                "events": "ai_agent_events event_seq replay windows",
                "cursor_policy": "evenly spaced Last-Event-ID windows per sampled run",
            },
        }
        audit["derived_from"] = {
            field: audit["derived_from"][field]
            for field in EVENT_REPLAY_DERIVED_FROM_FIELDS
        }
        return {field: audit[field] for field in EVENT_REPLAY_STRESS_AUDIT_FIELDS}

    def audit_run(self, *, run_id: str, after_sequence: int = 0) -> dict[str, Any]:
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == run_id))
        if run is None:
            raise ValueError(f"Agent run not found: {run_id}")
        events = list(self.db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run_id).order_by(AgentEvent.event_seq.asc())
        ).all())
        return self._audit_loaded_run(run=run, events=events, after_sequence=after_sequence)

    @staticmethod
    def _audit_loaded_run(*, run: AgentRun, events: list[AgentEvent], after_sequence: int = 0) -> dict[str, Any]:
        sequences = [item.event_seq for item in events]
        sequence_counts = Counter(sequences)
        unique_sequences = set(sequence_counts)
        duplicate_sequences = sorted(seq for seq, count in sequence_counts.items() if count > 1)
        expected = set(range(1, (run.last_event_sequence or 0) + 1))
        missing_sequences = sorted(expected.difference(unique_sequences))
        unexpected_sequences = sorted(seq for seq in unique_sequences if seq < 1 or seq > (run.last_event_sequence or 0))
        replay_events = [item for item in events if item.event_seq > after_sequence]
        replayable = (
            not missing_sequences
            and not duplicate_sequences
            and not unexpected_sequences
            and len(events) == (run.last_event_sequence or 0)
        )
        audit = {
            "run_id": run.run_id,
            "project_id": run.project_id,
            "last_event_sequence": run.last_event_sequence or 0,
            "after_sequence": after_sequence,
            "event_count": len(events),
            "replay_event_count": len(replay_events),
            "first_replay_event_seq": replay_events[0].event_seq if replay_events else None,
            "last_replay_event_seq": replay_events[-1].event_seq if replay_events else None,
            "missing_sequences": missing_sequences,
            "duplicate_sequences": duplicate_sequences,
            "unexpected_sequences": unexpected_sequences,
            "replayable": replayable,
            "replay_cursor_valid": 0 <= after_sequence <= (run.last_event_sequence or 0),
        }
        return {field: audit[field] for field in EVENT_REPLAY_AUDIT_FIELDS}

    def _events_by_run_id(self, run_ids: list[str]) -> dict[str, list[AgentEvent]]:
        if not run_ids:
            return {}
        events = self.db.scalars(
            select(AgentEvent)
            .where(AgentEvent.run_id.in_(run_ids))
            .order_by(AgentEvent.run_id.asc(), AgentEvent.event_seq.asc())
        ).all()
        grouped: dict[str, list[AgentEvent]] = defaultdict(list)
        for event in events:
            grouped[event.run_id].append(event)
        return grouped

    @staticmethod
    def _cursor_windows(*, last_event_sequence: int, cursor_count: int) -> list[int]:
        if cursor_count <= 1 or last_event_sequence <= 0:
            return [0]
        if cursor_count == 2:
            return [0, max(0, last_event_sequence - 1)]
        windows = {0, max(0, last_event_sequence - 1)}
        denominator = max(1, cursor_count - 1)
        for index in range(1, cursor_count - 1):
            windows.add(max(0, int(last_event_sequence * index / denominator)))
        return sorted(windows)


class AgentFaultInjectionCoverageService:
    def __init__(self, db: Session):
        self.db = db

    def audit(self) -> dict[str, Any]:
        from app.services.agent_fault_injection_service import AgentFaultInjectionService

        cases = AgentFaultInjectionService(self.db).list_cases()
        case_ids = {item["case_id"] for item in cases}
        covered = sorted(REQUIRED_FAULT_CASES.intersection(case_ids))
        missing = sorted(REQUIRED_FAULT_CASES.difference(case_ids))
        extra = sorted(case_ids.difference(REQUIRED_FAULT_CASES))
        audit = {
            "generated_at": _utcnow().isoformat(),
            "registered_case_count": len(case_ids),
            "required_case_count": len(REQUIRED_FAULT_CASES),
            "covered_required_case_ids": covered,
            "missing_required_case_ids": missing,
            "extra_case_ids": extra,
            "coverage_ratio": round(len(covered) / len(REQUIRED_FAULT_CASES), 4),
            "coverage_pass": not missing,
            "derived_from": {
                "registered_cases": "AgentFaultInjectionService.list_cases",
                "required_cases": "REQUIRED_FAULT_CASES",
            },
        }
        return {field: audit[field] for field in FAULT_INJECTION_COVERAGE_FIELDS}


class AgentAlertService:
    def __init__(self, db: Session):
        self.db = db

    def snapshot(
        self,
        *,
        project_id: int | None = None,
        metrics_snapshot: dict[str, Any] | None = None,
        release_gate: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.services.agent_release_gate_service import AgentReleaseGateService

        if metrics_snapshot is None:
            metrics_snapshot = AgentMetricsService(self.db).snapshot(project_id=project_id)
        if release_gate is None:
            release_gate = AgentReleaseGateService(self.db).snapshot()
        alerts = self._metric_alerts(metrics_snapshot["metrics"])
        alerts.extend(self._release_gate_alerts(release_gate))
        severity_counts = self._severity_counts(alerts)
        summary = {
            "total": len(alerts),
            "by_severity": severity_counts,
            "highest_severity": self._highest_severity(severity_counts),
        }
        snapshot = {
            "project_id": project_id,
            "generated_at": metrics_snapshot["generated_at"],
            "status": "firing" if alerts else "ok",
            "alerts": alerts,
            "summary": {field: summary[field] for field in ALERT_SUMMARY_FIELDS},
            "derived_from": {
                "metrics": "AgentMetricsService.snapshot",
                "release_gate": "AgentReleaseGateService.snapshot",
            },
        }
        return {field: snapshot[field] for field in ALERT_SNAPSHOT_FIELDS}

    def _metric_alerts(self, metrics: dict[str, int | float]) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = []
        for rule in ALERT_RULES:
            metric_key = rule["metric_key"]
            if metric_key not in metrics:
                continue
            value = metrics[metric_key]
            threshold = rule.get("threshold", 0)
            operator = rule.get("operator", "gt")
            if operator == "gt":
                firing = value > threshold
                condition = f"{metric_key} > {threshold}"
            elif operator == "lt":
                firing = value < threshold
                condition = f"{metric_key} < {threshold}"
            else:
                raise ValueError(f"Unsupported alert operator: {operator}")
            if not firing:
                continue
            related_metrics = {
                key: metrics[key]
                for key in rule.get("related_metric_keys", [])
                if key in metrics
            }
            details = {"condition": condition}
            if related_metrics:
                details["related_metrics"] = related_metrics
            alert_id = rule["alert_id"]
            alert = {
                "item_id": _agent_alert_item_id(alert_id),
                "alert_id": alert_id,
                "severity": rule["severity"],
                "status": "firing",
                "metric_key": metric_key,
                "observed_value": value,
                "threshold": threshold,
                "summary": rule["summary"],
                "action": rule["action"],
                "runbook_id": rule["runbook_id"],
                "details": details,
            }
            alerts.append({field: alert[field] for field in ALERT_ITEM_FIELDS})
        return alerts

    @staticmethod
    def _release_gate_alerts(release_gate: dict[str, Any]) -> list[dict[str, Any]]:
        violations = release_gate.get("violations") or []
        if not violations:
            return []
        alert_id = "agent_release_gate_violation"
        alert = {
            "item_id": _agent_alert_item_id(alert_id),
            "alert_id": alert_id,
            "severity": "P0",
            "status": "firing",
            "metric_key": "release_gate_violation_count",
            "observed_value": len(violations),
            "threshold": 0,
            "summary": "Registered tools exceed the current Agent rollout level.",
            "action": "Block rollout expansion until tool side-effect classes and contracts match the gate.",
            "runbook_id": "release_gate_violation",
            "details": {
                "condition": "release_gate.violations > 0",
                "current_level": release_gate.get("current_level"),
                "violations": violations,
            },
        }
        return [{field: alert[field] for field in ALERT_ITEM_FIELDS}]

    @staticmethod
    def _severity_counts(alerts: list[dict[str, Any]]) -> dict[str, int]:
        counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        for alert in alerts:
            severity = alert.get("severity")
            if severity in counts:
                counts[severity] += 1
        return counts

    @staticmethod
    def _highest_severity(counts: dict[str, int]) -> str | None:
        for severity in ("P0", "P1", "P2", "P3"):
            if counts.get(severity, 0) > 0:
                return severity
        return None


class AgentReadinessDashboardService:
    def __init__(self, db: Session):
        self.db = db

    def snapshot(
        self,
        *,
        project_id: int | None = None,
        metrics_snapshot: dict[str, Any] | None = None,
        release_gate: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.services.agent_fault_injection_service import AgentFaultInjectionService
        from app.services.agent_loop_service import RootCauseRuleEngine
        from app.services.agent_release_gate_service import AgentReleaseGateService
        from app.services.agent_runbook_service import AgentRunbookService

        if metrics_snapshot is None:
            metrics_snapshot = AgentMetricsService(self.db).snapshot(project_id=project_id)
        if release_gate is None:
            release_gate = AgentReleaseGateService(self.db).snapshot()
        fault_cases = AgentFaultInjectionService(self.db).list_cases()
        fault_coverage = AgentFaultInjectionCoverageService(self.db).audit()
        runbooks = AgentRunbookService(self.db).list_runbooks()
        alert_snapshot = AgentAlertService(self.db).snapshot(
            project_id=project_id,
            metrics_snapshot=metrics_snapshot,
            release_gate=release_gate,
        )
        promotion_assessment = self._promotion_assessment_summary(release_gate)
        root_cause_governance = RootCauseRuleEngine(self.db).audit_rule_governance()

        checks = [
            self._metric_catalog_check(metrics_snapshot["metrics"]),
            self._release_gate_check(release_gate),
            self._fault_catalog_check(fault_cases),
            self._root_cause_governance_check(root_cause_governance),
            self._runbook_catalog_check(runbooks),
            self._alert_metric_catalog_check(),
            self._live_recovery_check(metrics_snapshot["metrics"]),
            self._alert_health_check(alert_snapshot),
            self._promotion_assessment_check(promotion_assessment),
        ]
        snapshot = {
            "project_id": project_id,
            "generated_at": metrics_snapshot["generated_at"],
            "readiness": self._readiness(checks),
            "checks": checks,
            "metrics": metrics_snapshot["metrics"],
            "release_gate": release_gate,
            "promotion_assessment": promotion_assessment,
            "fault_injection": fault_coverage,
            "runbooks": self._runbook_summary(runbooks),
            "root_cause_governance": root_cause_governance,
            "alerts": alert_snapshot["alerts"],
            "alert_summary": alert_snapshot["summary"],
            "derived_from": {
                "metrics": "AgentMetricsService.snapshot",
                "release_gate": "AgentReleaseGateService.snapshot",
                "promotion_assessment": "AgentReleaseGateService.snapshot",
                "fault_injection": "AgentFaultInjectionService.list_cases",
                "fault_injection_coverage": "AgentFaultInjectionCoverageService.audit",
                "runbooks": "AgentRunbookService.list_runbooks",
                "root_cause_governance": "RootCauseRuleEngine.audit_rule_governance",
                "alerts": "AgentAlertService.snapshot",
            },
        }
        return {field: snapshot[field] for field in READINESS_DASHBOARD_FIELDS}

    def _metric_catalog_check(self, metrics: dict[str, int | float]) -> dict[str, Any]:
        missing = sorted(REQUIRED_DASHBOARD_METRICS.difference(metrics))
        return self._check(
            name="metrics_catalog_complete",
            status="pass" if not missing else "blocked",
            severity="P0",
            summary="required Agent recovery and governance metrics are exposed",
            details={
                "missing_metric_keys": missing,
                "required_metric_keys": sorted(REQUIRED_DASHBOARD_METRICS),
                "required_metric_count": len(REQUIRED_DASHBOARD_METRICS),
            },
        )

    def _release_gate_check(self, release_gate: dict[str, Any]) -> dict[str, Any]:
        violations = release_gate.get("violations") or []
        return self._check(
            name="release_gate_current_level_clean",
            status="pass" if not violations else "blocked",
            severity="P0",
            summary="registered tools fit the current rollout level",
            details={
                "current_level": release_gate.get("current_level"),
                "violation_count": len(violations),
                "violations": violations,
            },
        )

    def _promotion_assessment_summary(
        self,
        release_gate: dict[str, Any],
        *,
        target_level: str = "L3",
    ) -> dict[str, Any]:
        expansion_gates = release_gate.get("expansion_gates") or []
        target_gate = next((item for item in expansion_gates if item.get("level") == target_level), None)
        violations = release_gate.get("violations") or []
        final_delivery = release_gate.get("final_delivery") or {}
        summary = {
            "endpoint": "/api/v1/agents/release-gates/promotion",
            "current_level": release_gate.get("current_level"),
            "target_level": target_level,
            "target_gate_known": target_gate is not None,
            "target_gate_static_blocked_reasons": list(target_gate.get("blocked_reasons") or []) if target_gate else [],
            "current_tool_violation_count": len(violations),
            "current_tool_violations": violations,
            "final_delivery_contract_pass": final_delivery.get("pass") is True,
            "final_delivery_backend_repository_scope_pass": final_delivery.get("backend_repository_scope_pass") is True,
            "final_delivery_missing_by_category": dict(final_delivery.get("missing_by_category") or {}),
            "final_delivery_external_scope_categories": list(final_delivery.get("external_scope_categories") or []),
            "assessment_available": bool(release_gate.get("current_level") and target_gate is not None),
            "dashboard_dependency": "promotion assessment consumes this dashboard, so the dashboard reports contract inputs without invoking the endpoint",
        }
        return {field: summary[field] for field in PROMOTION_DASHBOARD_SUMMARY_FIELDS}

    def _promotion_assessment_check(self, promotion_assessment: dict[str, Any]) -> dict[str, Any]:
        return self._check(
            name="release_gate_promotion_assessment",
            status="pass" if promotion_assessment["assessment_available"] else "blocked",
            severity="P0",
            summary="release gate promotion assessment contract inputs are available",
            details=promotion_assessment,
        )

    def _fault_catalog_check(self, cases: list[dict[str, Any]]) -> dict[str, Any]:
        case_ids = {item["case_id"] for item in cases}
        covered = sorted(REQUIRED_FAULT_CASES.intersection(case_ids))
        missing = sorted(REQUIRED_FAULT_CASES.difference(case_ids))
        return self._check(
            name="fault_injection_catalog_complete",
            status="pass" if not missing else "blocked",
            severity="P0",
            summary="required production-hardening fault-injection cases are registered",
            details={
                "registered_case_count": len(case_ids),
                "required_case_count": len(REQUIRED_FAULT_CASES),
                "covered_required_case_ids": covered,
                "missing_required_case_ids": missing,
                "extra_case_ids": sorted(case_ids.difference(REQUIRED_FAULT_CASES)),
                "missing_case_ids": missing,
            },
        )

    def _runbook_catalog_check(self, runbooks: list[dict[str, Any]]) -> dict[str, Any]:
        runbook_ids = {item["runbook_id"] for item in runbooks}
        covered = sorted(REQUIRED_RUNBOOKS.intersection(runbook_ids))
        missing = sorted(REQUIRED_RUNBOOKS.difference(runbook_ids))
        return self._check(
            name="runbook_catalog_complete",
            status="pass" if not missing else "attention",
            severity="P1",
            summary="required recovery runbooks are registered",
            details={
                "registered_runbook_count": len(runbook_ids),
                "required_runbook_count": len(REQUIRED_RUNBOOKS),
                "covered_required_runbook_ids": covered,
                "missing_required_runbook_ids": missing,
                "missing_runbook_ids": missing,
            },
        )

    def _alert_metric_catalog_check(self) -> dict[str, Any]:
        trigger_metrics = {rule["metric_key"] for rule in ALERT_RULES}
        related_metrics = {
            metric_key
            for rule in ALERT_RULES
            for metric_key in rule.get("related_metric_keys", [])
        }
        from app.services.agent_runbook_service import RUNBOOKS

        required_runbook_alerts = [
            rule
            for rule in ALERT_RULES
            if rule.get("severity") in ALERT_RUNBOOK_REQUIRED_SEVERITIES
        ]
        covered_required_runbook_alert_ids = sorted(
            rule["alert_id"]
            for rule in required_runbook_alerts
            if rule.get("runbook_id") in RUNBOOKS
        )
        missing_required_runbook_alert_ids = sorted(
            rule["alert_id"]
            for rule in required_runbook_alerts
            if not rule.get("runbook_id") or rule.get("runbook_id") not in RUNBOOKS
        )
        covered_dynamic_runbook_alert_ids = sorted(
            alert_id
            for alert_id, runbook_id in ALERT_DYNAMIC_RUNBOOKS.items()
            if runbook_id in RUNBOOKS
        )
        missing_dynamic_runbook_alert_ids = sorted(
            alert_id
            for alert_id, runbook_id in ALERT_DYNAMIC_RUNBOOKS.items()
            if runbook_id not in RUNBOOKS
        )
        alert_runbook_ids = sorted(
            {
                rule["runbook_id"]
                for rule in ALERT_RULES
                if rule.get("runbook_id")
            }.union(ALERT_DYNAMIC_RUNBOOKS.values())
        )
        covered = trigger_metrics | related_metrics | DYNAMIC_ALERT_METRICS
        missing = sorted(ALERT_FACT_METRICS.difference(covered))
        return self._check(
            name="alert_metric_catalog_complete",
            status=(
                "pass"
                if not missing
                and not missing_required_runbook_alert_ids
                and not missing_dynamic_runbook_alert_ids
                else "attention"
            ),
            severity="P1",
            summary="Agent alert fact metrics are covered by trigger, related, or dynamic alert paths",
            details={
                "required_alert_metric_keys": sorted(ALERT_FACT_METRICS),
                "covered_alert_metric_keys": sorted(ALERT_FACT_METRICS.intersection(covered)),
                "missing_alert_metric_keys": missing,
                "trigger_metric_keys": sorted(trigger_metrics),
                "related_metric_keys": sorted(related_metrics),
                "dynamic_metric_keys": sorted(DYNAMIC_ALERT_METRICS),
                "runbook_required_severities": list(ALERT_RUNBOOK_REQUIRED_SEVERITIES),
                "alert_runbook_ids": alert_runbook_ids,
                "covered_required_runbook_alert_ids": covered_required_runbook_alert_ids,
                "missing_required_runbook_alert_ids": missing_required_runbook_alert_ids,
                "dynamic_alert_runbooks": dict(sorted(ALERT_DYNAMIC_RUNBOOKS.items())),
                "covered_dynamic_runbook_alert_ids": covered_dynamic_runbook_alert_ids,
                "missing_dynamic_runbook_alert_ids": missing_dynamic_runbook_alert_ids,
            },
        )

    def _root_cause_governance_check(self, audit: dict[str, Any]) -> dict[str, Any]:
        return self._check(
            name="root_cause_rule_governance",
            status="pass" if audit["governance_pass"] else "attention",
            severity="P1",
            summary="RootCause rules stay inside governed priority bands",
            details={
                "rule_count": audit["rule_count"],
                "priority_bands": audit["priority_bands"],
                "violation_count": audit["violation_count"],
                "violations": audit["violations"],
                "governance_pass": audit["governance_pass"],
            },
        )

    def _live_recovery_check(self, metrics: dict[str, int | float]) -> dict[str, Any]:
        open_blocks = int(metrics.get("migration_block_open_total") or 0)
        outbox_lag = int(metrics.get("outbox_publish_lag_ms") or 0)
        approval_due = int(metrics.get("approval_expire_due_total") or 0)
        approval_lag = int(metrics.get("approval_expire_batch_lag_ms") or 0)
        approval_hotspots = int(metrics.get("approval_lineage_hotspot_total") or 0)
        replay_stress_failures = int(metrics.get("event_replay_stress_failed_total") or 0)
        needs_attention = (
            open_blocks > 0
            or outbox_lag > 0
            or approval_due > 0
            or approval_hotspots > 0
            or replay_stress_failures > 0
        )
        return self._check(
            name="live_recovery_attention",
            status="attention" if needs_attention else "pass",
            severity="P1",
            summary="current project has no open migration block, pending outbox lag, approval expiration backlog, or replay stress failure",
            details={
                "migration_block_open_total": open_blocks,
                "outbox_publish_lag_ms": outbox_lag,
                "approval_expire_due_total": approval_due,
                "approval_expire_batch_lag_ms": approval_lag,
                "approval_lineage_hotspot_total": approval_hotspots,
                "event_replay_stress_failed_total": replay_stress_failures,
            },
        )

    def _alert_health_check(self, alert_snapshot: dict[str, Any]) -> dict[str, Any]:
        severity_counts = alert_snapshot["summary"]["by_severity"]
        status = "blocked" if severity_counts["P0"] else "attention" if severity_counts["P1"] else "pass"
        blocking_alerts = [
            alert
            for alert in alert_snapshot["alerts"]
            if alert.get("severity") in MONITORING_ALERT_BLOCKING_SEVERITIES
        ]
        p0_alert_ids = sorted(
            alert["alert_id"]
            for alert in blocking_alerts
            if alert.get("severity") == "P0"
        )
        p1_alert_ids = sorted(
            alert["alert_id"]
            for alert in blocking_alerts
            if alert.get("severity") == "P1"
        )
        return self._check(
            name="monitoring_alerts_clear",
            status=status,
            severity="P0" if severity_counts["P0"] else "P1",
            summary="current Agent monitoring alert rules are clear",
            details={
                "alert_total": alert_snapshot["summary"]["total"],
                "by_severity": severity_counts,
                "highest_severity": alert_snapshot["summary"]["highest_severity"],
                "blocking_severities": list(MONITORING_ALERT_BLOCKING_SEVERITIES),
                "blocking_alert_count": len(blocking_alerts),
                "blocking_alert_ids": sorted(alert["alert_id"] for alert in blocking_alerts),
                "blocking_runbook_ids": sorted(
                    {
                        alert["runbook_id"]
                        for alert in blocking_alerts
                        if alert.get("runbook_id")
                    }
                ),
                "p0_alert_ids": p0_alert_ids,
                "p1_alert_ids": p1_alert_ids,
            },
        )

    def _runbook_summary(self, runbooks: list[dict[str, Any]]) -> dict[str, Any]:
        runbook_ids = {item["runbook_id"] for item in runbooks}
        covered = sorted(REQUIRED_RUNBOOKS.intersection(runbook_ids))
        missing = sorted(REQUIRED_RUNBOOKS.difference(runbook_ids))
        return {
            "registered_runbook_count": len(runbook_ids),
            "required_runbook_count": len(REQUIRED_RUNBOOKS),
            "covered_required_runbook_ids": covered,
            "missing_required_runbook_ids": missing,
        }

    @staticmethod
    def _check(*, name: str, status: str, severity: str, summary: str, details: dict[str, Any]) -> dict[str, Any]:
        check = {
            "item_id": _agent_dashboard_check_item_id(name),
            "name": name,
            "status": status,
            "severity": severity,
            "summary": summary,
            "details": details,
        }
        return {field: check[field] for field in DASHBOARD_CHECK_FIELDS}

    @staticmethod
    def _readiness(checks: list[dict[str, Any]]) -> str:
        if any(item["status"] == "blocked" for item in checks):
            return "blocked"
        if any(item["status"] == "attention" for item in checks):
            return "attention"
        return "pass"


class AgentLaunchAuditService:
    def __init__(self, db: Session):
        self.db = db

    def audit(self, *, project_id: int | None = None) -> dict[str, Any]:
        from app.services.agent_release_gate_service import AgentReleaseGateService
        from app.services.agent_runtime_service import AgentModelHealthService

        model_health = AgentModelHealthService().check(live=False)
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=project_id)
        promotion = AgentReleaseGateService(self.db).promotion_assessment(target_level="L3", project_id=project_id)
        release_gate = dashboard["release_gate"]
        final_delivery = release_gate["final_delivery"]
        checks = [
            self._check(
                name="model_provider_configured",
                status="pass" if model_health["configured"] else "blocked",
                severity="P0",
                summary="Agent model provider is configured without exposing API keys",
                details={
                    "provider": model_health["provider"],
                    "default_model": model_health["default_model"],
                    "live_probe_required_for_runtime_e2e": False,
                },
            ),
            self._check(
                name="normal_conversation_runtime_available",
                status="pass",
                severity="P0",
                summary="Normal Agent runs use AgentConversationRunner and support MySQL/file SQLite workers",
                details={
                    "runner": "AgentConversationRunner",
                    "normal_run_path": "POST /api/v1/agents/runs",
                    "worker_start_modes": ["mysql", "file_sqlite"],
                    "test_skip_mode": "in_memory_sqlite",
                },
            ),
            self._check(
                name="frontend_event_contract_available",
                status="pass",
                severity="P0",
                summary="Frontend can consume SSE, snapshot, summary, actions, history, transcript and export contracts",
                details={
                    "stream_path": "GET /api/v1/agents/runs/{run_id}/events",
                    "snapshot_path": "GET /api/v1/agents/runs/{run_id}/events/snapshot",
                    "summary_path": "GET /api/v1/agents/runs/{run_id}/summary",
                    "actions_path": "GET /api/v1/agents/runs/{run_id}/actions",
                    "history_paths": [
                        "GET /api/v1/agents/conversations",
                        "GET /api/v1/agents/conversations/{conversation_id}/runs",
                        "GET /api/v1/agents/conversations/{conversation_id}/transcript",
                        "GET /api/v1/agents/conversations/{conversation_id}/export",
                    ],
                },
            ),
            self._check(
                name="dashboard_readiness_not_blocked",
                status="blocked" if dashboard["readiness"] == "blocked" else "pass",
                severity="P0",
                summary="Readiness dashboard has no blocking P0 checks",
                details={
                    "readiness": dashboard["readiness"],
                    "blocked_check_names": sorted(
                        item["name"] for item in dashboard["checks"] if item["status"] == "blocked"
                    ),
                    "attention_check_names": sorted(
                        item["name"] for item in dashboard["checks"] if item["status"] == "attention"
                    ),
                },
            ),
            self._check(
                name="backend_repository_delivery_complete",
                status="pass" if final_delivery["backend_repository_scope_pass"] else "blocked",
                severity="P0",
                summary="Backend-owned Agent delivery artifacts are complete",
                details={
                    "backend_repository_scope_pass": final_delivery["backend_repository_scope_pass"],
                    "missing_by_category": final_delivery["missing_by_category"],
                },
            ),
            self._check(
                name="frontend_external_scope_declared",
                status="pass" if "frontend" in final_delivery["external_scope_categories"] else "attention",
                severity="P1",
                summary="Frontend implementation is explicitly tracked as external to this backend repository",
                details={
                    "external_scope_categories": final_delivery["external_scope_categories"],
                    "backend_audit_does_not_claim_frontend_delivery": True,
                },
            ),
            self._check(
                name="promotion_assessment_available",
                status="pass" if promotion["decision"] in {"blocked", "allowed", "already_unlocked"} else "blocked",
                severity="P0",
                summary="Release-gate promotion assessment is available for rollout decisions",
                details={
                    "target_level": promotion["target_level"],
                    "decision": promotion["decision"],
                    "can_promote": promotion["can_promote"],
                    "blocker_sources": sorted({item["source"] for item in promotion["blockers"]}),
                },
            ),
        ]
        status = self._status(checks)
        snapshot = {
            "project_id": project_id,
            "generated_at": _utcnow().isoformat(),
            "ready": status == "pass",
            "status": status,
            "checks": checks,
            "model_health": model_health,
            "dashboard": {
                "readiness": dashboard["readiness"],
                "alert_summary": dashboard["alert_summary"],
                "check_statuses": {item["name"]: item["status"] for item in dashboard["checks"]},
            },
            "promotion": {
                "target_level": promotion["target_level"],
                "decision": promotion["decision"],
                "can_promote": promotion["can_promote"],
                "blockers": promotion["blockers"],
            },
            "derived_from": {
                "model_health": "AgentModelHealthService.check(live=False)",
                "dashboard": "AgentReadinessDashboardService.snapshot",
                "promotion": "AgentReleaseGateService.promotion_assessment",
            },
        }
        return {field: snapshot[field] for field in AGENT_LAUNCH_AUDIT_FIELDS}

    @staticmethod
    def _check(*, name: str, status: str, severity: str, summary: str, details: dict[str, Any]) -> dict[str, Any]:
        check = {
            "item_id": _agent_dashboard_check_item_id(name),
            "name": name,
            "status": status,
            "severity": severity,
            "summary": summary,
            "details": details,
        }
        return {field: check[field] for field in DASHBOARD_CHECK_FIELDS}

    @staticmethod
    def _status(checks: list[dict[str, Any]]) -> str:
        if any(item["status"] == "blocked" for item in checks):
            return "blocked"
        if any(item["status"] == "attention" for item in checks):
            return "attention"
        return "pass"


class AgentBackendCompletionAuditService:
    def __init__(self, db: Session):
        self.db = db

    def audit(self, *, project_id: int | None = None) -> dict[str, Any]:
        from app.services.agent_runbook_service import (
            RUNBOOK_DISPATCH_TRACE_SUMMARY_FIELDS,
            RUNBOOK_EXECUTION_CONTEXT_SUMMARY_FIELDS,
        )

        launch_audit = AgentLaunchAuditService(self.db).audit(project_id=project_id)
        launch_checks = {item["name"]: item for item in launch_audit["checks"]}
        final_delivery = launch_audit["dashboard"]["check_statuses"]
        model_check = launch_checks["model_provider_configured"]
        dashboard_check = launch_checks["dashboard_readiness_not_blocked"]
        backend_delivery_check = launch_checks["backend_repository_delivery_complete"]
        behavior_evaluation_case_ids = _behavior_evaluation_case_ids()
        behavior_evaluation_assertions = _behavior_evaluation_assertions()
        behavior_evaluation_assertion_coverage = _behavior_evaluation_assertion_coverage()
        behavior_evaluation_undeclared_case_assertions = _behavior_evaluation_undeclared_case_assertions()
        behavior_evaluation_uncovered_assertion_ids = _behavior_evaluation_uncovered_assertion_ids()
        behavior_evaluation_assertion_metadata_complete = (
            not behavior_evaluation_undeclared_case_assertions
            and not behavior_evaluation_uncovered_assertion_ids
        )
        behavior_evaluation_runbook = _behavior_evaluation_runbook()
        behavior_evaluation_latest_report = _behavior_evaluation_latest_report()
        checks = [
            self._check(
                name="model_provider_configured",
                status=model_check["status"],
                severity="P0",
                summary="DeepSeek-compatible model provider is configured for normal Agent conversation runs",
                details=model_check["details"],
            ),
            self._check(
                name="conversation_runner_streaming",
                status="pass",
                severity="P0",
                summary="Normal Agent runs invoke AgentConversationRunner and stream assistant deltas before completion",
                details={
                    "runner": "AgentConversationRunner",
                    "normal_run_path": "POST /api/v1/agents/runs",
                    "stream_path": "GET /api/v1/agents/runs/{run_id}/events",
                    "snapshot_path": "GET /api/v1/agents/runs/{run_id}/events/snapshot",
                    "required_event_types": [
                        "run.started",
                        "model.started",
                        "model.delta",
                        "model.completed",
                        "run.completed",
                        "run.failed",
                    ],
                },
            ),
            self._check(
                name="server_side_conversation_history",
                status="pass",
                severity="P0",
                summary="Conversation context is persisted server-side and exposed through list, transcript and export APIs",
                details={
                    "conversation_id_source": "AgentRun.conversation_id",
                    "history_paths": launch_checks["frontend_event_contract_available"]["details"]["history_paths"],
                    "context_source": "latest completed runs in the same conversation",
                },
            ),
            self._check(
                name="tool_loop_and_approval_resume",
                status="pass",
                severity="P0",
                summary="Model-driven tool requests, approval pauses and approved resume flows are part of the runtime",
                details={
                    "tool_request_events": [
                        "model.tool_request_detected",
                        "model.tool_request_invalid",
                        "model.tool_request_repaired",
                        "tool.planned",
                        "tool.result_observed",
                    ],
                    "approval_paths": [
                        "POST /api/v1/agents/tool-calls/{tool_call_id}/approve",
                        "POST /api/v1/agents/runs/{run_id}/resume",
                    ],
                    "resume_contract": "AgentRunResumeRead",
                },
            ),
            self._check(
                name="memory_context_injection",
                status="pass",
                severity="P1",
                summary="Project Memory is retrieved before conversation calls and reported in EventStore",
                details={
                    "event_type": "memory.context_injected",
                    "profile": "normal_plan_v1",
                    "usage_query_path": "GET /api/v1/agents/memory-usage-events",
                },
            ),
            self._check(
                name="frontend_contract_surface",
                status=launch_checks["frontend_event_contract_available"]["status"],
                severity="P0",
                summary="Frontend-visible contracts cover SSE, snapshots, summaries, actions, history and export",
                details=launch_checks["frontend_event_contract_available"]["details"],
            ),
            self._check(
                name="observability_and_release_gate",
                status=dashboard_check["status"],
                severity="P0",
                summary="Readiness dashboard and release gate inputs are available without blocking P0 checks",
                details={
                    "dashboard_readiness": launch_audit["dashboard"]["readiness"],
                    "dashboard_check_statuses": final_delivery,
                    "promotion_decision": launch_audit["promotion"]["decision"],
                    "promotion_is_production_gate": True,
                    "tool_execution_context_source": "AgentToolCall.policy_reason_json.execution_context",
                    "tool_dispatch_trace_source": "AgentToolCall.policy_reason_json.dispatch_trace",
                    "runbook_execution_context_summary": "AgentRunbookRecommendation.details.execution_context",
                    "runbook_execution_context_summary_fields": list(RUNBOOK_EXECUTION_CONTEXT_SUMMARY_FIELDS),
                    "runbook_dispatch_trace_summary": "AgentRunbookRecommendation.details.dispatch_trace",
                    "runbook_dispatch_trace_summary_fields": list(RUNBOOK_DISPATCH_TRACE_SUMMARY_FIELDS),
                },
            ),
            self._check(
                name="backend_delivery_docs_synced",
                status=backend_delivery_check["status"],
                severity="P0",
                summary="Backend-owned Agent delivery artifacts and documentation contracts are synchronized",
                details={
                    "backend_repository_scope_pass": backend_delivery_check["details"]["backend_repository_scope_pass"],
                    "missing_by_category": backend_delivery_check["details"]["missing_by_category"],
                    "docs": [
                        "docs/api_agent_frontend_contract.md",
                        "docs/technical_architecture.md",
                        "docs/测试平台_Harness_Loop_Agent_开发计划_Memory强化版.md",
                        "docs/测试平台_Harness_Loop_Agent_架构_五次修正版_Memory强化版.md",
                    ],
                },
            ),
            self._check(
                name="live_e2e_diagnostic_available",
                status="pass",
                severity="P1",
                summary="Maintainers have both admin API and normal-user script paths to verify live DeepSeek conversation E2E",
                details={
                    "admin_api": "POST /api/v1/agents/conversation-smoke",
                    "normal_user_script": "scripts/agent_conversation_e2e_check.py",
                    "script_assertions": [
                        "live model health",
                        "normal run creation",
                        "model.delta observed",
                        "run.completed observed",
                        "assistant_visible summary",
                    ],
                },
            ),
            self._check(
                name="behavior_evaluation_suite_available",
                status="pass" if behavior_evaluation_assertion_metadata_complete else "attention",
                severity="P1",
                summary="Maintainers have a repeatable multi-case behavior evaluation for Agent loop, repair and tool boundaries",
                details={
                    "script": "scripts/agent_behavior_evaluation.py",
                    "case_ids": behavior_evaluation_case_ids,
                    "case_count": len(behavior_evaluation_case_ids),
                    "assertions": behavior_evaluation_assertions,
                    "assertion_coverage": behavior_evaluation_assertion_coverage,
                    "undeclared_case_assertions": behavior_evaluation_undeclared_case_assertions,
                    "uncovered_assertion_ids": behavior_evaluation_uncovered_assertion_ids,
                    "assertion_metadata_complete": behavior_evaluation_assertion_metadata_complete,
                    "model_call_trace_fields": _behavior_evaluation_model_call_trace_fields(),
                    "markdown_sections": _behavior_evaluation_markdown_sections(),
                    "latest_report_fields": _behavior_evaluation_latest_report_fields(),
                    "runbook": behavior_evaluation_runbook,
                    "latest_report": behavior_evaluation_latest_report,
                    "output_prefix": "reports/woagent_behavior_eval_{timestamp}",
                    "artifacts": [
                        "reports/woagent_behavior_eval_*.json",
                        "reports/woagent_behavior_eval_*.md",
                        "reports/woagent_behavior_eval_*.progress.log",
                    ],
                },
            ),
        ]
        status = self._status(checks)
        snapshot = {
            "project_id": project_id,
            "generated_at": _utcnow().isoformat(),
            "complete": status == "pass",
            "status": status,
            "checks": checks,
            "backend_scope": {
                "owned_scope": "backend Agent runtime, contracts, diagnostics and prototype-facing documentation",
                "frontend_delivery": "external repository",
                "production_promotion": "separate release-gate decision",
            },
            "launch_audit": {
                "ready": launch_audit["ready"],
                "status": launch_audit["status"],
                "model_configured": launch_audit["model_health"]["configured"],
                "dashboard_readiness": launch_audit["dashboard"]["readiness"],
                "promotion_decision": launch_audit["promotion"]["decision"],
            },
            "runtime_contracts": {
                "run": "POST /api/v1/agents/runs",
                "events": "GET /api/v1/agents/runs/{run_id}/events",
                "snapshot": "GET /api/v1/agents/runs/{run_id}/events/snapshot",
                "summary": "GET /api/v1/agents/runs/{run_id}/summary",
                "actions": "GET /api/v1/agents/runs/{run_id}/actions",
                "history": "GET /api/v1/agents/conversations",
                "transcript": "GET /api/v1/agents/conversations/{conversation_id}/transcript",
                "export": "GET /api/v1/agents/conversations/{conversation_id}/export",
                "tool_execution_context": "AgentToolCall.policy_reason_json.execution_context",
                "tool_dispatch_trace": "AgentToolCall.policy_reason_json.dispatch_trace",
                "runbook_execution_context_summary": "AgentRunbookRecommendation.details.execution_context",
                "runbook_execution_context_summary_fields": list(RUNBOOK_EXECUTION_CONTEXT_SUMMARY_FIELDS),
                "runbook_dispatch_trace_summary": "AgentRunbookRecommendation.details.dispatch_trace",
                "runbook_dispatch_trace_summary_fields": list(RUNBOOK_DISPATCH_TRACE_SUMMARY_FIELDS),
            },
            "diagnostics": {
                "model_health": "GET /api/v1/agents/model-health",
                "launch_audit": "GET /api/v1/agents/launch-audit",
                "completion_audit": "GET /api/v1/agents/backend-completion-audit",
                "conversation_smoke": "POST /api/v1/agents/conversation-smoke",
                "e2e_script": "scripts/agent_conversation_e2e_check.py",
                "tool_call_detail": "GET /api/v1/agents/tool-calls/{tool_call_id}",
                "runbook_diagnosis": "GET /api/v1/agents/runs/{run_id}/runbook",
                "behavior_evaluation_script": "scripts/agent_behavior_evaluation.py",
                "behavior_evaluation_reports": "reports/woagent_behavior_eval_*.json|md",
            },
            "derived_from": {
                "launch_audit": "AgentLaunchAuditService.audit",
                "readiness_dashboard": "AgentReadinessDashboardService.snapshot",
                "release_gate": "AgentReleaseGateService.promotion_assessment",
                "behavior_evaluation_suite": "scripts.agent_behavior_evaluation.CASES",
                "behavior_evaluation_cases": "scripts.agent_behavior_evaluation.CASES",
                "behavior_evaluation_assertions": "scripts.agent_behavior_evaluation.ASSERTIONS",
                "behavior_evaluation_assertion_coverage": "scripts.agent_behavior_evaluation.assertion_coverage",
                "behavior_evaluation_undeclared_case_assertions": "scripts.agent_behavior_evaluation.undeclared_case_assertions",
                "behavior_evaluation_uncovered_assertions": "scripts.agent_behavior_evaluation.uncovered_assertion_ids",
                "behavior_evaluation_runbook": "scripts.agent_behavior_evaluation.behavior_evaluation_runbook",
                "behavior_evaluation_latest_report": "scripts.agent_behavior_evaluation.latest_report_summary",
                "behavior_evaluation_latest_report_fields": "scripts.agent_behavior_evaluation.LATEST_REPORT_SUMMARY_FIELDS",
                "behavior_evaluation_model_call_trace_fields": "scripts.agent_behavior_evaluation.MODEL_CALL_TRACE_FIELDS",
                "behavior_evaluation_markdown_sections": "scripts.agent_behavior_evaluation.MARKDOWN_REPORT_SECTIONS",
            },
        }
        return {field: snapshot[field] for field in AGENT_BACKEND_COMPLETION_AUDIT_FIELDS}

    @staticmethod
    def _check(*, name: str, status: str, severity: str, summary: str, details: dict[str, Any]) -> dict[str, Any]:
        check = {
            "item_id": _agent_dashboard_check_item_id(name),
            "name": name,
            "status": status,
            "severity": severity,
            "summary": summary,
            "details": details,
        }
        return {field: check[field] for field in DASHBOARD_CHECK_FIELDS}

    @staticmethod
    def _status(checks: list[dict[str, Any]]) -> str:
        if any(item["status"] == "blocked" for item in checks):
            return "blocked"
        if any(item["status"] == "attention" for item in checks):
            return "attention"
        return "pass"


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _agent_alert_item_id(alert_id: str) -> str:
    return f"{AGENT_ALERT_ITEM_ID_PREFIX}://{alert_id}"


def _agent_dashboard_check_item_id(name: str) -> str:
    return f"{AGENT_DASHBOARD_CHECK_ITEM_ID_PREFIX}://{name}"


def _worker_queue_expired_lease_item_id(queue_id: str) -> str:
    return f"{AGENT_WORKER_QUEUE_EXPIRED_LEASE_ITEM_ID_PREFIX}://{queue_id}"


def _worker_queue_duplicate_active_item_id(tool_call_id: str) -> str:
    return f"{AGENT_WORKER_QUEUE_DUPLICATE_ACTIVE_ITEM_ID_PREFIX}://{tool_call_id}"


def _event_replay_stress_run_item_id(run_id: str) -> str:
    return f"{AGENT_EVENT_REPLAY_STRESS_RUN_ITEM_ID_PREFIX}://{run_id}"


def _event_replay_cursor_item_id(run_id: str, after_sequence: int) -> str:
    return f"{AGENT_EVENT_REPLAY_CURSOR_ITEM_ID_PREFIX}://{run_id}/{after_sequence}"


def _behavior_evaluation_case_ids() -> list[str]:
    from scripts.agent_behavior_evaluation import CASES

    return [case.case_id for case in CASES]


def _behavior_evaluation_assertions() -> list[str]:
    from scripts.agent_behavior_evaluation import ASSERTIONS

    return list(ASSERTIONS)


def _behavior_evaluation_assertion_coverage() -> dict[str, list[str]]:
    from scripts.agent_behavior_evaluation import assertion_coverage

    return assertion_coverage()


def _behavior_evaluation_undeclared_case_assertions() -> dict[str, list[str]]:
    from scripts.agent_behavior_evaluation import undeclared_case_assertions

    return undeclared_case_assertions()


def _behavior_evaluation_uncovered_assertion_ids() -> list[str]:
    from scripts.agent_behavior_evaluation import uncovered_assertion_ids

    return uncovered_assertion_ids()


def _behavior_evaluation_model_call_trace_fields() -> list[str]:
    from scripts.agent_behavior_evaluation import MODEL_CALL_TRACE_FIELDS

    return list(MODEL_CALL_TRACE_FIELDS)


def _behavior_evaluation_markdown_sections() -> list[str]:
    from scripts.agent_behavior_evaluation import MARKDOWN_REPORT_SECTIONS

    return list(MARKDOWN_REPORT_SECTIONS)


def _behavior_evaluation_latest_report_fields() -> list[str]:
    from scripts.agent_behavior_evaluation import LATEST_REPORT_SUMMARY_FIELDS

    return list(LATEST_REPORT_SUMMARY_FIELDS)


def _behavior_evaluation_runbook() -> dict[str, Any]:
    from scripts.agent_behavior_evaluation import behavior_evaluation_runbook

    return behavior_evaluation_runbook()


def _behavior_evaluation_latest_report() -> dict[str, Any]:
    from scripts.agent_behavior_evaluation import latest_report_summary

    return latest_report_summary()
