from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import (
    AgentApproval,
    AgentContextBuild,
    AgentEvent,
    AgentLoopObservation,
    AgentMigrationBlock,
    AgentRun,
    AgentToolCall,
)
from app.models.user import User
from app.services.agent_reconcile_service import CheckpointFreshnessGate
from app.services.permission_service import PermissionService


AGENT_RUNBOOK_ITEM_ID_PREFIX = "agent-runbook"
AGENT_RUNBOOK_RECOMMENDATION_ITEM_ID_PREFIX = "agent-runbook-recommendation"

RUNBOOKS: dict[str, dict[str, Any]] = {
    "tool_call_uncertain": {
        "title": "Runbook: uncertain ToolCall recovery",
        "trigger": "A ToolCall is uncertain or reconciling.",
        "severity": "P1",
        "steps": [
            "Inspect effect_submission_state and backend_effect_capability.",
            "Trigger run reconcile before retrying any side effect.",
            "If reconcile returns conflict or effect_committed+not_found, move to manual intervention.",
        ],
        "safe_api_actions": ["POST /api/v1/agents/runs/{run_id}/reconcile"],
    },
    "migration_blocked": {
        "title": "Runbook: migration_blocked handling",
        "trigger": "Run has open migration blocks or status=migration_blocked.",
        "severity": "P1",
        "steps": [
            "List migration blocks and inspect backend contract/schema details.",
            "Deploy or register a compatible adapter before resolving the block.",
            "Resolve the block and require checkpoint freshness gate before resume.",
            "If the run is terminal, resolving the block preserves terminal status and re-enables reconcile instead of resume.",
        ],
        "safe_api_actions": [
            "GET /api/v1/agents/runs/{run_id}/migration-blocks",
            "POST /api/v1/agents/runs/{run_id}/migration-blocks/{block_id}/resolve",
        ],
    },
    "backend_capability_degraded": {
        "title": "Runbook: backend capability degradation",
        "trigger": "A ToolCall uses legacy_reconcile_only or legacy_no_receipt backend effect capability.",
        "severity": "P1",
        "steps": [
            "Inspect the ToolCall backend_effect_capability and operation-level BackendExecutionContract.",
            "For high-risk legacy_no_receipt operations, keep the call in manual intervention or require reapproval.",
            "Upgrade the backend operation to receipt_first or idempotency_index_only before rollout expansion.",
        ],
        "safe_api_actions": [
            "GET /api/v1/agents/tool-calls/{tool_call_id}",
            "GET /api/v1/agents/release-gates",
            "GET /api/v1/agents/dashboard",
        ],
    },
    "approval_stale": {
        "title": "Runbook: approval stale or epoch conflict",
        "trigger": "approval.approve_conflict event or pending approval with stale client data.",
        "severity": "P1",
        "steps": [
            "Refresh ToolCall detail and current approval lineage.",
            "Compare input_hash/runtime_snapshot_id/resource_scope_hash/approval_epoch.",
            "Ask the approver to review the latest pending approval; do not approve old input.",
        ],
        "safe_api_actions": [
            "GET /api/v1/agents/tool-calls/{tool_call_id}",
            "POST /api/v1/agents/tool-calls/{tool_call_id}/approve",
            "POST /api/v1/agents/tool-calls/{tool_call_id}/reject",
        ],
    },
    "checkpoint_stale": {
        "title": "Runbook: checkpoint stale handling",
        "trigger": "Checkpoint freshness gate is too_old or requires evidence rebuild.",
        "severity": "P1",
        "steps": [
            "Do not resume high-risk execution directly from a stale checkpoint.",
            "Fetch latest evidence or rebuild decision context.",
            "Resume only after freshness gate returns continue_from_checkpoint.",
        ],
        "safe_api_actions": [
            "GET /api/v1/agents/runs/{run_id}/migration-blocks",
            "POST /api/v1/agents/runs/{run_id}/context-builds",
            "POST /api/v1/agents/runs/{run_id}/resume",
            "GET /api/v1/agents/tool-calls/{tool_call_id}",
        ],
    },
    "outbox_publish_lag": {
        "title": "Runbook: Agent outbox publish lag",
        "trigger": "Agent outbox has pending or failed messages beyond the publish lag threshold.",
        "severity": "P1",
        "steps": [
            "Run the outbox publisher with a bounded batch size.",
            "Inspect failed rows and dead-letter errors before retrying external notifications.",
            "Confirm EventStore rows remain durable even if notification delivery is delayed.",
        ],
        "safe_api_actions": ["POST /api/v1/agents/outbox/publish"],
    },
    "event_replay_recovery": {
        "title": "Runbook: EventStore and SSE replay recovery",
        "trigger": "Event replay audit detects gaps, cursor failures, or high-concurrency replay failures.",
        "severity": "P1",
        "steps": [
            "Run single-run replay audit for the affected run.",
            "Run project replay stress audit to identify invalid cursor windows.",
            "Do not rely on Last-Event-ID replay until event_seq continuity and replay windows are clean.",
        ],
        "safe_api_actions": [
            "GET /api/v1/agents/runs/{run_id}/events/replay-audit",
            "GET /api/v1/agents/events/replay-stress-audit",
        ],
    },
    "fault_injection_coverage": {
        "title": "Runbook: required fault-injection coverage",
        "trigger": "Required Agent production hardening fault cases are missing.",
        "severity": "P1",
        "steps": [
            "Run the fault-injection coverage audit and inspect missing_required_case_ids.",
            "Register or repair missing required cases before expanding rollout.",
            "Re-run the coverage audit and dashboard readiness check before promotion.",
        ],
        "safe_api_actions": [
            "GET /api/v1/agents/fault-injections/coverage",
            "POST /api/v1/agents/fault-injections/run",
        ],
    },
    "worker_queue_recovery": {
        "title": "Runbook: WorkerQueue lease and duplicate claim recovery",
        "trigger": "WorkerQueue audit detects expired leases or duplicate active leases.",
        "severity": "P1",
        "steps": [
            "Run WorkerQueue audit and locate affected ToolCall ids.",
            "Recover expired leases through the worker queue recovery path.",
            "Pause workers and repair duplicate active queue rows before retrying duplicated ToolCalls.",
        ],
        "safe_api_actions": ["GET /api/v1/agents/worker-queue/audit"],
    },
    "context_linkage_repair": {
        "title": "Runbook: context and observation linkage repair",
        "trigger": "LoopObservation references a missing decision ContextBuild.",
        "severity": "P1",
        "steps": [
            "Inspect the affected LoopObservation and decision_context_build_id.",
            "Rebuild or repair the decision context linkage before using diagnostics.",
            "Verify dashboard monitoring alerts clear after the linkage is corrected.",
        ],
        "safe_api_actions": [
            "GET /api/v1/agents/runs/{run_id}/context-builds",
            "GET /api/v1/agents/runs/{run_id}/loop-observations",
        ],
    },
    "agent_runtime_loop_repair": {
        "title": "Runbook: Agent runtime loop repair and stop handling",
        "trigger": "AgentConversationRunner records runtime repair or stop LoopObservations.",
        "severity": "P2",
        "steps": [
            "Inspect the LoopObservation root_cause_rule_id, stop_action_reason, and mitigation_action.",
            "For repair observations, verify the next model/tool turn followed the mitigation path.",
            "For stop observations, decide whether to extend limits, change tool inputs, or hand off to a human.",
        ],
        "safe_api_actions": [
            "GET /api/v1/agents/runs/{run_id}/loop-observations",
            "GET /api/v1/agents/tool-calls/{tool_call_id}",
        ],
    },
    "root_cause_rule_missing": {
        "title": "Runbook: missing RootCause governance rule",
        "trigger": "Loop reasons were observed without an explicit RootCause rule.",
        "severity": "P1",
        "steps": [
            "Inspect the observed reason keys and affected LoopObservations.",
            "Add or activate an explicit RootCause rule with priority band and mitigation.",
            "Re-run diagnostics and verify root_cause_rule_missing_total returns to zero.",
        ],
        "safe_api_actions": ["GET /api/v1/agents/runs/{run_id}/loop-observations"],
    },
    "memory_evidence_ref_violation": {
        "title": "Runbook: Memory EvidenceRef governance violation",
        "trigger": "Memory bypassed EvidenceRef wrapping or high-risk action depended only on Memory.",
        "severity": "P0",
        "steps": [
            "Block or pause the affected flow before executing high-risk actions.",
            "Repair MemoryEvidenceAdapter or ContextBuilder usage so every memory enters as a memory EvidenceRef.",
            "Require non-memory decision evidence before approving high-risk actions.",
        ],
        "safe_api_actions": [
            "GET /api/v1/agents/memories",
            "POST /api/v1/agents/memories/retrieve",
            "GET /api/v1/agents/memory-staleness-events",
        ],
    },
    "release_gate_violation": {
        "title": "Runbook: release gate rollout violation",
        "trigger": "Registered tools exceed the current Agent rollout level.",
        "severity": "P0",
        "steps": [
            "Inspect the release gate snapshot and current tool matrix violations.",
            "Block promotion until every registered tool side-effect class is allowed by the current rollout level.",
            "Either downgrade the tool rollout exposure or complete the required approval/reconcile/contract gates before expanding.",
        ],
        "safe_api_actions": [
            "GET /api/v1/agents/release-gates",
            "GET /api/v1/agents/release-gates/promotion",
            "GET /api/v1/agents/dashboard",
        ],
    },
}

RUNBOOK_FIELDS = (
    "item_id",
    "runbook_id",
    "title",
    "trigger",
    "severity",
    "steps",
    "safe_api_actions",
)
RUNBOOK_DIAGNOSIS_FIELDS = ("run_id", "run_status", "recommendations", "runbooks")
RUNBOOK_RECOMMENDATION_FIELDS = (
    "item_id",
    "runbook_id",
    "reason",
    "severity",
    "action",
    "tool_call_id",
    "details",
)
RUNBOOK_RECOMMENDATION_REQUIRED_FIELDS = {"item_id", "runbook_id", "reason", "severity", "action", "details"}
RUNBOOK_RECOMMENDATION_OPTIONAL_FIELDS = {"tool_call_id"}
RUNBOOK_DIAGNOSIS_RECOMMENDATION_RUNBOOK_IDS = set(RUNBOOKS)
RUNBOOK_EXECUTION_CONTEXT_SUMMARY_FIELDS = (
    "execution_context_version_hash",
    "execution_context_hash",
    "tool_call_id",
    "run_id",
    "runtime_snapshot_id",
    "tool_name",
    "tool_version",
    "worker_id",
    "tool_status",
    "execution_phase",
    "effect_submission_state",
    "effect_boundary_crossed",
    "backend_name",
    "backend_operation",
    "backend_contract_version",
    "backend_request_schema_hash",
    "backend_output_schema_hash",
    "reconcile_contract_version",
    "result_adapter_version",
    "backend_effect_capability",
    "resolved_side_effect_class",
    "resolved_replay_policy",
    "approval_state",
    "approval_lineage_id",
    "approval_epoch",
    "approved_approval_id",
    "approved_by",
    "input_hash",
    "output_hash",
    "recovery_decision",
    "error_code",
    "error_message_hash",
)
RUNBOOK_DISPATCH_TRACE_SUMMARY_FIELDS = (
    "dispatch_trace_version_hash",
    "dispatch_trace_hash",
    "tool_call_id",
    "run_id",
    "runtime_snapshot_id",
    "tool_name",
    "tool_version",
    "schema_hash",
    "manifest_hash",
    "router",
    "runtime",
    "backend_handler",
    "backend_name",
    "backend_operation",
    "backend_contract_version",
    "resolved_side_effect_class",
    "resolved_replay_policy",
    "status",
    "effect_submission_state",
)
RUNBOOK_EVENT_PAYLOAD_SUMMARY_VERSION = "runbook_event_payload_summary_v1"
RUNBOOK_EVENT_PAYLOAD_PREVIEW_MAX_CHARS = 1000
RUNBOOK_EVENT_PAYLOAD_TRUNCATION_MARKER = "[runbook_event_payload_truncated]"
RUNBOOK_EVENT_PAYLOAD_KEY_LIMIT = 40
RUNTIME_LOOP_REPAIR_STOP_REASONS = {
    "tool_prerequisite_missing",
    "tool_request_format_invalid",
    "required_tool_followup_missing",
    "max_iterations",
    "same_failure_no_progress",
}
CHECKPOINT_FRESHNESS_SAFE_ACTIONS = {
    "continue_from_checkpoint": "POST /api/v1/agents/runs/{run_id}/resume",
    "replan_from_latest_safe_state": "POST /api/v1/agents/runs/{run_id}/context-builds",
    "migration_block": "GET /api/v1/agents/runs/{run_id}/migration-blocks",
    "fetch_evidence_and_rebuild_context": "POST /api/v1/agents/runs/{run_id}/context-builds",
    "materialize_latest_evidence": "POST /api/v1/agents/runs/{run_id}/context-builds",
    "revalidate_before_side_effect": "POST /api/v1/agents/runs/{run_id}/context-builds",
    "supersede_or_refresh_approval": "GET /api/v1/agents/tool-calls/{tool_call_id}",
    "refresh_permissions_or_manual_review": "GET /api/v1/agents/tool-calls/{tool_call_id}",
}


class AgentRunbookService:
    def __init__(self, db: Session):
        self.db = db
        self.permission_service = PermissionService(db)

    def list_runbooks(self) -> list[dict[str, Any]]:
        return [self._runbook_item(runbook_id, payload) for runbook_id, payload in sorted(RUNBOOKS.items())]

    def diagnose_run(self, *, run_id: str, current_user: User) -> dict[str, Any]:
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == run_id))
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
        self.permission_service.require_project_access(current_user, run.project_id)
        recommendations = []
        recommendations.extend(self._uncertain_recommendations(run))
        recommendations.extend(self._migration_recommendations(run))
        recommendations.extend(self._approval_recommendations(run))
        recommendations.extend(self._backend_capability_recommendations(run))
        recommendations.extend(self._context_linkage_recommendations(run))
        recommendations.extend(self._runtime_loop_repair_recommendations(run))
        recommendations.extend(self._root_cause_rule_recommendations(run))
        recommendations.extend(self._memory_evidence_recommendations(run))
        recommendations.extend(self._release_gate_recommendations())
        checkpoint = CheckpointFreshnessGate(self.db).evaluate(run=run, current_user=current_user)
        if checkpoint.get("result") != "fresh":
            recommendations.append({
                "runbook_id": "checkpoint_stale",
                "reason": checkpoint.get("reason"),
                "severity": RUNBOOKS["checkpoint_stale"]["severity"],
                "action": self._checkpoint_safe_action(checkpoint),
                "details": checkpoint,
            })
        diagnosis = {
            "run_id": run.run_id,
            "run_status": run.status,
            "recommendations": [
                self._recommendation_item(item, run_id=run.run_id)
                for item in recommendations
            ],
            "runbooks": self.list_runbooks(),
        }
        return {field: diagnosis[field] for field in RUNBOOK_DIAGNOSIS_FIELDS}

    @staticmethod
    def _runbook_item(runbook_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        item = {
            "item_id": f"{AGENT_RUNBOOK_ITEM_ID_PREFIX}://{runbook_id}",
            "runbook_id": runbook_id,
            **payload,
        }
        return {field: item[field] for field in RUNBOOK_FIELDS}

    @staticmethod
    def _recommendation_item(recommendation: dict[str, Any], *, run_id: str) -> dict[str, Any]:
        item = {
            **recommendation,
            "item_id": _runbook_recommendation_item_id(run_id=run_id, recommendation=recommendation),
            "tool_call_id": recommendation.get("tool_call_id"),
        }
        return {field: item[field] for field in RUNBOOK_RECOMMENDATION_FIELDS}

    @staticmethod
    def _checkpoint_safe_action(checkpoint: dict[str, Any]) -> str:
        return CHECKPOINT_FRESHNESS_SAFE_ACTIONS.get(
            checkpoint.get("action"),
            "POST /api/v1/agents/runs/{run_id}/context-builds",
        )

    @staticmethod
    def _execution_context_summary(call: AgentToolCall) -> dict[str, Any] | None:
        execution_context = (call.policy_reason_json or {}).get("execution_context")
        if not isinstance(execution_context, dict):
            return None
        summary = {
            field: execution_context[field]
            for field in RUNBOOK_EXECUTION_CONTEXT_SUMMARY_FIELDS
            if field in execution_context
        }
        return summary or None

    @staticmethod
    def _dispatch_trace_summary(call: AgentToolCall) -> dict[str, Any] | None:
        dispatch_trace = (call.policy_reason_json or {}).get("dispatch_trace")
        if not isinstance(dispatch_trace, dict):
            return None
        summary = {
            field: dispatch_trace[field]
            for field in RUNBOOK_DISPATCH_TRACE_SUMMARY_FIELDS
            if field in dispatch_trace
        }
        return summary or None

    def _details_with_execution_context(
        self,
        call: AgentToolCall,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        execution_context = self._execution_context_summary(call)
        dispatch_trace = self._dispatch_trace_summary(call)
        if execution_context is None and dispatch_trace is None:
            return details
        enriched = dict(details)
        if execution_context is not None:
            enriched["execution_context"] = execution_context
        if dispatch_trace is not None:
            enriched["dispatch_trace"] = dispatch_trace
        return enriched

    @staticmethod
    def _event_payload_details(event: AgentEvent) -> dict[str, Any]:
        payload = event.payload_json if isinstance(event.payload_json, dict) else {}
        payload_json = json.dumps(
            payload,
            ensure_ascii=False,
            default=str,
            sort_keys=True,
            separators=(",", ":"),
        )
        payload_preview = payload_json[:RUNBOOK_EVENT_PAYLOAD_PREVIEW_MAX_CHARS]
        payload_truncated = len(payload_json) > RUNBOOK_EVENT_PAYLOAD_PREVIEW_MAX_CHARS
        if payload_truncated:
            payload_preview += RUNBOOK_EVENT_PAYLOAD_TRUNCATION_MARKER
        return {
            "event_id": event.id,
            "event_seq": event.event_seq,
            "payload_summary_version": RUNBOOK_EVENT_PAYLOAD_SUMMARY_VERSION,
            "payload_keys": sorted(str(key) for key in payload)[:RUNBOOK_EVENT_PAYLOAD_KEY_LIMIT],
            "payload_preview": payload_preview,
            "payload_truncated": payload_truncated,
            "payload_size_chars": len(payload_json),
            "payload_hash": hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
            "full_payload_reference": "AgentEvent.payload_json",
        }

    def _uncertain_recommendations(self, run: AgentRun) -> list[dict[str, Any]]:
        calls = list(
            self.db.scalars(
                select(AgentToolCall)
                .where(
                    AgentToolCall.run_id == run.run_id,
                    AgentToolCall.status.in_(["uncertain", "reconciling"]),
                )
                .order_by(AgentToolCall.step_index.asc(), AgentToolCall.attempt_index.asc())
            ).all()
        )
        return [
            {
                "runbook_id": "tool_call_uncertain",
                "reason": "tool_call_requires_reconcile",
                "severity": RUNBOOKS["tool_call_uncertain"]["severity"],
                "action": "POST /api/v1/agents/runs/{run_id}/reconcile",
                "tool_call_id": call.tool_call_id,
                "details": self._details_with_execution_context(call, {
                    "status": call.status,
                    "effect_submission_state": call.effect_submission_state,
                    "backend_effect_capability": call.backend_effect_capability,
                    "backend_operation": call.backend_operation,
                }),
            }
            for call in calls
        ]

    def _migration_recommendations(self, run: AgentRun) -> list[dict[str, Any]]:
        run_terminal = run.status in {"completed", "failed", "cancelled"}
        open_blocks = list(
            self.db.scalars(
                select(AgentMigrationBlock)
                .where(AgentMigrationBlock.run_id == run.run_id, AgentMigrationBlock.status == "open")
                .order_by(AgentMigrationBlock.created_at.asc())
            ).all()
        )
        if not open_blocks and run.status != "migration_blocked":
            return []
        return [
            {
                "runbook_id": "migration_blocked",
                "reason": "open_migration_block_on_terminal_run" if run_terminal else "open_migration_block",
                "severity": RUNBOOKS["migration_blocked"]["severity"],
                "action": "GET /api/v1/agents/runs/{run_id}/migration-blocks",
                "tool_call_id": block.tool_call_id,
                "details": {
                    "block_id": block.block_id,
                    "tool_call_id": block.tool_call_id,
                    "block_type": block.block_type,
                    "reason": block.reason,
                    "run_status": run.status,
                    "run_terminal": run_terminal,
                    "resolve_preserves_terminal_run": run_terminal,
                    "post_resolve_next_action": "reconcile_run" if run_terminal else "checkpoint_freshness_then_resume",
                    "tool_call_status_after_resolve": "reconciling",
                    "backend_name": block.backend_name,
                    "backend_operation": block.backend_operation,
                    "backend_contract_version": block.backend_contract_version,
                },
            }
            for block in open_blocks
        ] or [{
            "runbook_id": "migration_blocked",
            "reason": "run_status_migration_blocked_without_open_block",
            "severity": RUNBOOKS["migration_blocked"]["severity"],
            "action": "GET /api/v1/agents/runs/{run_id}/migration-blocks",
            "details": {"run_status": run.status},
        }]

    def _approval_recommendations(self, run: AgentRun) -> list[dict[str, Any]]:
        pending = list(
            self.db.scalars(
                select(AgentApproval)
                .where(AgentApproval.run_id == run.run_id, AgentApproval.approval_status == "pending")
                .order_by(AgentApproval.created_at.asc())
            ).all()
        )
        conflicts = list(
            self.db.scalars(
                select(AgentEvent)
                .where(AgentEvent.run_id == run.run_id, AgentEvent.event_type == "approval.approve_conflict")
                .order_by(AgentEvent.event_seq.desc())
            ).all()
        )
        recommendations: list[dict[str, Any]] = []
        for approval in pending:
            recommendations.append({
                "runbook_id": "approval_stale",
                "reason": "pending_approval_requires_fresh_review",
                "severity": RUNBOOKS["approval_stale"]["severity"],
                "action": "GET /api/v1/agents/tool-calls/{tool_call_id}",
                "tool_call_id": approval.tool_call_id,
                "details": {
                    "approval_id": approval.approval_id,
                    "approval_lineage_id": approval.approval_lineage_id,
                    "approval_epoch": approval.approval_epoch,
                    "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
                },
            })
        for event in conflicts[:3]:
            recommendations.append({
                "runbook_id": "approval_stale",
                "reason": "approval_conflict_event_seen",
                "severity": RUNBOOKS["approval_stale"]["severity"],
                "action": "GET /api/v1/agents/tool-calls/{tool_call_id}",
                "tool_call_id": (event.payload_json or {}).get("tool_call_id"),
                "details": self._event_payload_details(event),
            })
        return recommendations

    def _backend_capability_recommendations(self, run: AgentRun) -> list[dict[str, Any]]:
        calls = list(
            self.db.scalars(
                select(AgentToolCall)
                .where(
                    AgentToolCall.run_id == run.run_id,
                    AgentToolCall.backend_effect_capability.in_([
                        "legacy_reconcile_only",
                        "legacy_no_receipt",
                    ]),
                )
                .order_by(AgentToolCall.step_index.asc(), AgentToolCall.attempt_index.asc())
            ).all()
        )
        return [
            {
                "runbook_id": "backend_capability_degraded",
                "reason": "backend_effect_capability_degraded",
                "severity": RUNBOOKS["backend_capability_degraded"]["severity"],
                "action": "GET /api/v1/agents/tool-calls/{tool_call_id}",
                "tool_call_id": call.tool_call_id,
                "details": self._details_with_execution_context(call, {
                    "backend_effect_capability": call.backend_effect_capability,
                    "backend_operation": call.backend_operation,
                    "backend_name": call.backend_name,
                    "status": call.status,
                    "recovery_decision": call.recovery_decision,
                    "error_code": call.error_code,
                }),
            }
            for call in calls
        ]

    def _context_linkage_recommendations(self, run: AgentRun) -> list[dict[str, Any]]:
        observations = list(
            self.db.scalars(
                select(AgentLoopObservation)
                .where(AgentLoopObservation.run_id == run.run_id)
                .order_by(AgentLoopObservation.iteration.asc(), AgentLoopObservation.step_index.asc())
            ).all()
        )
        if not observations:
            return []
        build_ids = {
            build_id
            for build_id in self.db.scalars(
                select(AgentContextBuild.context_build_id).where(AgentContextBuild.run_id == run.run_id)
            ).all()
        }
        missing = [
            observation
            for observation in observations
            if observation.decision_context_build_id not in build_ids
        ]
        return [
            {
                "runbook_id": "context_linkage_repair",
                "reason": "loop_observation_missing_decision_context_build",
                "severity": RUNBOOKS["context_linkage_repair"]["severity"],
                "action": "GET /api/v1/agents/runs/{run_id}/loop-observations",
                "details": {
                    "observation_id": observation.observation_id,
                    "decision_context_build_id": observation.decision_context_build_id,
                    "iteration": observation.iteration,
                    "step_index": observation.step_index,
                    "root_cause_rule_id": observation.root_cause_rule_id,
                },
            }
            for observation in missing[:5]
        ]

    def _runtime_loop_repair_recommendations(self, run: AgentRun) -> list[dict[str, Any]]:
        observations = list(
            self.db.scalars(
                select(AgentLoopObservation)
                .where(
                    AgentLoopObservation.run_id == run.run_id,
                    AgentLoopObservation.stop_action_reason.in_(RUNTIME_LOOP_REPAIR_STOP_REASONS),
                )
                .order_by(AgentLoopObservation.iteration.asc(), AgentLoopObservation.step_index.asc())
            ).all()
        )
        return [
            {
                "runbook_id": "agent_runtime_loop_repair",
                "reason": "runtime_loop_repair_or_stop_observed",
                "severity": RUNBOOKS["agent_runtime_loop_repair"]["severity"],
                "action": "GET /api/v1/agents/runs/{run_id}/loop-observations",
                "details": {
                    "observation_id": observation.observation_id,
                    "iteration": observation.iteration,
                    "step_index": observation.step_index,
                    "next_action": observation.next_action,
                    "stop_action_reason": observation.stop_action_reason,
                    "stop_reasons_all": observation.stop_reasons_all_json,
                    "root_cause_rule_id": observation.root_cause_rule_id,
                    "root_cause_primary": observation.root_cause_primary,
                    "mitigation_action": observation.mitigation_action,
                    "observation_source": (observation.observation_json or {}).get("source"),
                },
            }
            for observation in observations[:5]
        ]

    def _root_cause_rule_recommendations(self, run: AgentRun) -> list[dict[str, Any]]:
        observations = list(
            self.db.scalars(
                select(AgentLoopObservation)
                .where(
                    AgentLoopObservation.run_id == run.run_id,
                    AgentLoopObservation.root_cause_primary == "root_cause_rule_missing",
                )
                .order_by(AgentLoopObservation.iteration.asc(), AgentLoopObservation.step_index.asc())
            ).all()
        )
        return [
            {
                "runbook_id": "root_cause_rule_missing",
                "reason": "loop_observation_used_root_cause_fallback",
                "severity": RUNBOOKS["root_cause_rule_missing"]["severity"],
                "action": "GET /api/v1/agents/runs/{run_id}/loop-observations",
                "details": {
                    "observation_id": observation.observation_id,
                    "root_cause_rule_id": observation.root_cause_rule_id,
                    "root_cause_primary": observation.root_cause_primary,
                    "stop_action_reason": observation.stop_action_reason,
                    "stop_reasons_all": observation.stop_reasons_all_json,
                },
            }
            for observation in observations[:5]
        ]

    def _memory_evidence_recommendations(self, run: AgentRun) -> list[dict[str, Any]]:
        events = list(
            self.db.scalars(
                select(AgentEvent)
                .where(
                    AgentEvent.run_id == run.run_id,
                    AgentEvent.event_type == "memory.bypassed_evidence_ref",
                )
                .order_by(AgentEvent.event_seq.desc())
            ).all()
        )
        high_risk_memory_calls = list(
            self.db.scalars(
                select(AgentToolCall)
                .where(
                    AgentToolCall.run_id == run.run_id,
                    AgentToolCall.error_code == "high_risk_action_cannot_depend_only_on_memory",
                )
                .order_by(AgentToolCall.step_index.asc(), AgentToolCall.attempt_index.asc())
            ).all()
        )
        recommendations = [
            {
                "runbook_id": "memory_evidence_ref_violation",
                "reason": "memory_bypassed_evidence_ref_event_seen",
                "severity": RUNBOOKS["memory_evidence_ref_violation"]["severity"],
                "action": "GET /api/v1/agents/memories",
                "details": self._event_payload_details(event),
            }
            for event in events[:5]
        ]
        recommendations.extend(
            {
                "runbook_id": "memory_evidence_ref_violation",
                "reason": "high_risk_action_depended_only_on_memory",
                "severity": RUNBOOKS["memory_evidence_ref_violation"]["severity"],
                "action": "GET /api/v1/agents/tool-calls/{tool_call_id}",
                "tool_call_id": call.tool_call_id,
                "details": {
                    "status": call.status,
                    "error_code": call.error_code,
                    "backend_operation": call.backend_operation,
                    "decision_context_build_id": call.decision_context_build_id,
                },
            }
            for call in high_risk_memory_calls[:5]
        )
        return recommendations

    def _release_gate_recommendations(self) -> list[dict[str, Any]]:
        from app.services.agent_release_gate_service import AgentReleaseGateService

        release_gate = AgentReleaseGateService(self.db).snapshot()
        violations = release_gate.get("violations") or []
        if not violations:
            return []
        return [{
            "runbook_id": "release_gate_violation",
            "reason": "current_tool_matrix_has_rollout_violations",
            "severity": RUNBOOKS["release_gate_violation"]["severity"],
            "action": "GET /api/v1/agents/release-gates",
            "details": {
                "current_level": release_gate.get("current_level"),
                "violation_count": len(violations),
                "violations": violations[:5],
            },
        }]


def _runbook_recommendation_item_id(*, run_id: str, recommendation: dict[str, Any]) -> str:
    runbook_id = str(recommendation.get("runbook_id") or "unknown")
    details = recommendation.get("details") or {}
    stable_detail_keys = (
        "action",
        "approval_id",
        "approval_lineage_id",
        "block_id",
        "context_build_id",
        "current_level",
        "event_id",
        "event_seq",
        "observation_id",
        "result",
        "root_cause_rule_id",
        "run_status",
        "violation_count",
    )
    material = {
        "runbook_id": recommendation.get("runbook_id"),
        "reason": recommendation.get("reason"),
        "action": recommendation.get("action"),
        "tool_call_id": recommendation.get("tool_call_id"),
        "details": {
            key: details[key]
            for key in stable_detail_keys
            if key in details
        },
    }
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    return f"{AGENT_RUNBOOK_RECOMMENDATION_ITEM_ID_PREFIX}://{run_id}/{runbook_id}/{digest}"
