from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import ProjectPermission
from app.models.agent import (
    AgentCheckpoint,
    AgentEvent,
    AgentMigrationBlock,
    AgentOutbox,
    AgentRun,
    AgentToolCall,
    ProjectMemory,
)
from app.models.project import ProjectMember, ProjectMemberPermission
from app.models.user import User
from app.schemas.agent import (
    AgentApprovalDecisionRequest,
    AgentContextBuildCreateRequest,
    AgentLoopObservationCreateRequest,
    AgentRunCreateRequest,
    AgentToolCallCreateRequest,
    ReconcileResult,
)
from app.services.agent_approval_service import ApprovalExpireScanner, ApprovalService
from app.services.agent_loop_service import ContextBuilder, LoopController
from app.services.agent_memory_service import MemoryManager, MemoryStalenessWorker
from app.services.agent_observability_service import AgentOutboxPublisher
from app.services.agent_reconcile_service import CheckpointFreshnessGate, MigrationCoordinator, ReconcileWorker
from app.services.agent_runtime_service import (
    AgentRuntimeService,
    AgentWorkerQueueService,
    ExecutionLedgerService,
    ToolExecutor,
)


FAULT_CASES = (
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
)
FAULT_INJECTION_CASE_FIELDS = (
    "case_id",
    "description",
    "expected",
)
FAULT_INJECTION_RUN_FIELDS = (
    "project_id",
    "requested",
    "passed",
    "failed",
    "results",
)
FAULT_INJECTION_RESULT_FIELDS = (
    "case_id",
    "run_id",
    "tool_call_id",
    "passed",
    "observed",
    "evidence",
)


class AgentFaultInjectionService:
    def __init__(self, db: Session):
        self.db = db
        self.runtime = AgentRuntimeService(db)
        self.ledger = ExecutionLedgerService(db)

    def list_cases(self) -> list[dict[str, Any]]:
        cases = [
            {
                "case_id": "send_intent_not_found",
                "description": "Validate send_intent_recorded + reconcile not_found becomes failed_retryable.",
                "expected": {"tool_status": "failed_retryable", "recovery_decision": "safe_retry_same_idempotency_key"},
            },
            {
                "case_id": "transport_sent_not_found",
                "description": "Validate transport_sent_observed + idempotency_index_only not_found remains uncertain with backoff.",
                "expected": {"tool_status": "uncertain", "recovery_decision": "reconcile_backoff"},
            },
            {
                "case_id": "backend_accepted_not_found",
                "description": "Validate backend_accepted + reconcile not_found becomes a manual incident.",
                "expected": {"tool_status": "manual_intervention", "recovery_decision": "backend_accepted_not_found_incident"},
            },
            {
                "case_id": "effect_committed_reconcile_reuse",
                "description": "Validate effect_committed recovery reuses the recorded downstream result instead of replaying.",
                "expected": {"tool_status": "succeeded", "recovery_decision": "mark_succeeded_from_reconcile"},
            },
            {
                "case_id": "tool_succeeded_eventstore_write_failed",
                "description": "Validate a backend success followed by EventStore write failure becomes uncertain and reconcile-required.",
                "expected": {"tool_status": "uncertain", "recovery_decision": "reconcile_required_after_eventstore_failure"},
            },
            {
                "case_id": "outbox_publish_failure",
                "description": "Validate EventStore remains durable while Outbox publishing moves to dead_letter after retry exhaustion.",
                "expected": {"outbox_dead_letter": 1, "event_count_min": 1},
            },
            {
                "case_id": "reconcile_conflict",
                "description": "Validate reconcile conflict forces manual_intervention instead of blind retry.",
                "expected": {"tool_status": "manual_intervention", "recovery_decision": "idempotency_conflict"},
            },
            {
                "case_id": "unsupported_schema_version",
                "description": "Validate unsupported backend contract creates an open migration block and blocks the run.",
                "expected": {"tool_status": "needs_migration", "run_status": "migration_blocked"},
            },
            {
                "case_id": "migration_block_resolve_checkpoint_continue",
                "description": "Validate resolving a migration block runs Freshness Gate, resumes the run, and preserves completed tools.",
                "expected": {"run_status": "running", "freshness_action": "continue_from_checkpoint"},
            },
            {
                "case_id": "legacy_no_receipt_high_risk",
                "description": "Validate legacy_no_receipt high-risk calls are forced to manual_intervention.",
                "expected": {"tool_status": "manual_intervention", "recovery_decision": "legacy_no_receipt_high_risk_manual"},
            },
            {
                "case_id": "approval_epoch_conflict",
                "description": "Validate stale approval epoch records approval.approve_conflict and returns 409.",
                "expected": {"error_code": "approval_epoch_conflict", "event_type": "approval.approve_conflict"},
            },
            {
                "case_id": "approval_supersede_replacement_atomic",
                "description": "Validate replacement tool_call creation and old approval supersede happen in one lineage transaction.",
                "expected": {"old_approval_status": "superseded", "replacement_approval_status": "pending"},
            },
            {
                "case_id": "approval_expired_before_approve",
                "description": "Validate approval expiration scanner blocks the tool before a stale approval can execute.",
                "expected": {"approval_status": "expired", "tool_status": "manual_intervention"},
            },
            {
                "case_id": "checkpoint_stale",
                "description": "Validate stale checkpoints require replan rather than direct resume.",
                "expected": {"freshness_result": "too_old", "freshness_action": "replan_from_latest_safe_state"},
            },
            {
                "case_id": "context_heavy_evidence_incomplete",
                "description": "Validate heavy context degradation with omitted required evidence records a high-risk stop reason.",
                "expected": {"required_evidence_complete": False, "root_cause_rule_id": "RC_CONTEXT_OMITTED_HIGH_RISK"},
            },
            {
                "case_id": "loop_observation_decision_context_binding",
                "description": "Validate LoopObservation binds the explicit decision ContextBuild when multiple builds exist in one iteration.",
                "expected": {"bound_to_latest_decision_build": True},
            },
            {
                "case_id": "evidence_historical_volatile_excluded",
                "description": "Validate historical volatile latest evidence is excluded from active replay policy.",
                "expected": {"replay_policy": "reuse_allowed", "historical_volatile_excluded_count": 1},
            },
            {
                "case_id": "evidence_mixed_volatile_frozen_requires_revalidation",
                "description": "Validate active mixed volatile and frozen evidence resolves to require_revalidation.",
                "expected": {"replay_policy": "require_revalidation", "mixed_volatile_frozen": True},
            },
            {
                "case_id": "memory_contradiction",
                "description": "Validate critical memory contradiction demotes memory into needs_revalidation.",
                "expected": {"memory_status": "needs_revalidation", "contradiction_count": 1},
            },
            {
                "case_id": "memory_stale_evidence_watch",
                "description": "Validate EvidenceWatch-linked external changes mark dependent memory stale.",
                "expected": {"memory_status": "needs_revalidation", "touched": 1},
            },
            {
                "case_id": "memory_bypassed_evidence_ref",
                "description": "Validate declared memory usage without a matching memory EvidenceRef is rejected and counted.",
                "expected": {"error_code": "memory_bypassed_evidence_ref", "event_type": "memory.bypassed_evidence_ref"},
            },
            {
                "case_id": "duplicate_idempotency_key",
                "description": "Validate duplicate idempotency_key is blocked and reported as one ledger row.",
                "expected": {"duplicate_event_count": 1, "tool_call_reused": True},
            },
            {
                "case_id": "permission_revoked_before_execution",
                "description": "Validate execute-time permission revocation fails the tool before backend execution.",
                "expected": {"tool_status": "failed", "error_code": "permission_revoked_before_execution"},
            },
            {
                "case_id": "worker_queue_reconcile_required",
                "description": "Validate uncertain/reconciling ToolCalls accidentally queued for execution are blocked until reconcile.",
                "expected": {"queue_status": "failed", "error_code": "tool_call_uncertain_reconcile_required"},
            },
            {
                "case_id": "root_cause_rule_missing",
                "description": "Validate unclassified loop reasons fall back to the explicit missing-rule governance row.",
                "expected": {"root_cause_rule_id": "RC_RULE_MISSING", "root_cause_primary": "root_cause_rule_missing"},
            },
            {
                "case_id": "high_risk_memory_only_blocked",
                "description": "Validate high-risk actions depending only on memory evidence are blocked before backend execution.",
                "expected": {"tool_status": "manual_intervention", "error_code": "high_risk_action_cannot_depend_only_on_memory"},
            },
        ]
        return [{field: item[field] for field in FAULT_INJECTION_CASE_FIELDS} for item in cases]

    def run_cases(
        self,
        *,
        project_id: int,
        case_ids: list[str] | None,
        current_user: User,
    ) -> dict[str, Any]:
        requested = case_ids or list(FAULT_CASES)
        invalid = sorted(set(requested) - set(FAULT_CASES))
        if invalid:
            raise HTTPException(status_code=422, detail={"code": "unknown_fault_injection_case", "case_ids": invalid})
        results = [
            self._result_item(self._run_case(case_id=case_id, project_id=project_id, current_user=current_user))
            for case_id in requested
        ]
        summary = {
            "project_id": project_id,
            "requested": len(requested),
            "passed": sum(1 for item in results if item["passed"]),
            "failed": sum(1 for item in results if not item["passed"]),
            "results": results,
        }
        return {field: summary[field] for field in FAULT_INJECTION_RUN_FIELDS}

    def _run_case(self, *, case_id: str, project_id: int, current_user: User) -> dict[str, Any]:
        handlers = {
            "send_intent_not_found": self._send_intent_not_found,
            "transport_sent_not_found": self._transport_sent_not_found,
            "backend_accepted_not_found": self._backend_accepted_not_found,
            "effect_committed_reconcile_reuse": self._effect_committed_reconcile_reuse,
            "tool_succeeded_eventstore_write_failed": self._tool_succeeded_eventstore_write_failed,
            "outbox_publish_failure": self._outbox_publish_failure,
            "reconcile_conflict": self._reconcile_conflict,
            "unsupported_schema_version": self._unsupported_schema_version,
            "migration_block_resolve_checkpoint_continue": self._migration_block_resolve_checkpoint_continue,
            "legacy_no_receipt_high_risk": self._legacy_no_receipt_high_risk,
            "approval_epoch_conflict": self._approval_epoch_conflict,
            "approval_supersede_replacement_atomic": self._approval_supersede_replacement_atomic,
            "approval_expired_before_approve": self._approval_expired_before_approve,
            "checkpoint_stale": self._checkpoint_stale,
            "context_heavy_evidence_incomplete": self._context_heavy_evidence_incomplete,
            "loop_observation_decision_context_binding": self._loop_observation_decision_context_binding,
            "evidence_historical_volatile_excluded": self._evidence_historical_volatile_excluded,
            "evidence_mixed_volatile_frozen_requires_revalidation": self._evidence_mixed_volatile_frozen_requires_revalidation,
            "memory_contradiction": self._memory_contradiction,
            "memory_stale_evidence_watch": self._memory_stale_evidence_watch,
            "memory_bypassed_evidence_ref": self._memory_bypassed_evidence_ref,
            "duplicate_idempotency_key": self._duplicate_idempotency_key,
            "permission_revoked_before_execution": self._permission_revoked_before_execution,
            "worker_queue_reconcile_required": self._worker_queue_reconcile_required,
            "root_cause_rule_missing": self._root_cause_rule_missing,
            "high_risk_memory_only_blocked": self._high_risk_memory_only_blocked,
        }
        return handlers[case_id](project_id=project_id, current_user=current_user)

    def _send_intent_not_found(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        run, call = self._uncertain_call(project_id=project_id, current_user=current_user, effect_state="send_intent_recorded")
        summary = ReconcileWorker(self.db).reconcile_run(run_id=run.run_id, current_user=current_user)
        refreshed = self._get_call(call.tool_call_id)
        return self._result(
            case_id="send_intent_not_found",
            run=run,
            call=refreshed,
            passed=refreshed.status == "failed_retryable" and refreshed.recovery_decision == "safe_retry_same_idempotency_key",
            evidence={"reconcile_summary": summary},
        )

    def _transport_sent_not_found(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        run, call = self._uncertain_call(project_id=project_id, current_user=current_user, effect_state="transport_sent_observed")
        summary = ReconcileWorker(self.db).reconcile_run(run_id=run.run_id, current_user=current_user)
        refreshed = self._get_call(call.tool_call_id)
        attempts = self._reconcile_attempt_count(refreshed.tool_call_id)
        return self._result(
            case_id="transport_sent_not_found",
            run=run,
            call=refreshed,
            passed=(
                refreshed.status == "uncertain"
                and refreshed.recovery_decision == "reconcile_backoff"
                and refreshed.backend_effect_capability == "idempotency_index_only"
                and refreshed.effect_submission_state == "transport_sent_observed"
                and refreshed.downstream_acceptance_id is None
                and attempts >= 1
            ),
            evidence={
                "reconcile_summary": summary,
                "reconcile_attempt_count": attempts,
                "backend_effect_capability": refreshed.backend_effect_capability,
                "effect_submission_state": refreshed.effect_submission_state,
                "downstream_acceptance_id": refreshed.downstream_acceptance_id,
            },
        )

    def _backend_accepted_not_found(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        run, call = self._uncertain_call(project_id=project_id, current_user=current_user, effect_state="backend_accepted")
        call.backend_effect_capability = "receipt_first"
        self.db.commit()
        summary = ReconcileWorker(self.db).reconcile_run(run_id=run.run_id, current_user=current_user)
        refreshed = self._get_call(call.tool_call_id)
        return self._result(
            case_id="backend_accepted_not_found",
            run=run,
            call=refreshed,
            passed=(
                refreshed.status == "manual_intervention"
                and refreshed.recovery_decision == "backend_accepted_not_found_incident"
                and refreshed.error_code == "reconcile_not_found_after_commit"
            ),
            evidence={"reconcile_summary": summary},
        )

    def _effect_committed_reconcile_reuse(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        run, call = self._uncertain_call(project_id=project_id, current_user=current_user, effect_state="effect_committed")
        call.output_json_redacted = {"recovered_from": "ledger_output", "idempotency_key": call.idempotency_key}
        call.external_resource_type = "project-service:read_context"
        call.external_resource_id = f"fault-{call.tool_call_id}"
        self.db.commit()
        summary = ReconcileWorker(self.db).reconcile_run(run_id=run.run_id, current_user=current_user)
        refreshed = self._get_call(call.tool_call_id)
        return self._result(
            case_id="effect_committed_reconcile_reuse",
            run=run,
            call=refreshed,
            passed=(
                refreshed.status == "succeeded"
                and refreshed.recovery_decision == "mark_succeeded_from_reconcile"
                and refreshed.external_resource_id == f"fault-{call.tool_call_id}"
            ),
            evidence={"reconcile_summary": summary, "output_hash": refreshed.output_hash},
        )

    def _tool_succeeded_eventstore_write_failed(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        run = self.runtime.create_run(
            payload=AgentRunCreateRequest(project_id=project_id, intent="fault injection: tool_succeeded_eventstore_write_failed"),
            current_user=current_user,
        )
        call = self.ledger.create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": project_id},
                step_index=0,
            ),
            current_user=current_user,
            enqueue=True,
        )
        refreshed = ToolExecutor(self.db, runtime_factory=_EventStoreFailingRuntime).execute_next(
            worker_id="fault-injection-eventstore"
        )
        if refreshed is None:
            refreshed = self._get_call(call.tool_call_id)
        return self._result(
            case_id="tool_succeeded_eventstore_write_failed",
            run=run,
            call=refreshed,
            passed=(
                refreshed.status == "uncertain"
                and refreshed.effect_submission_state == "effect_committed"
                and refreshed.recovery_decision == "reconcile_required_after_eventstore_failure"
                and refreshed.error_code == "eventstore_write_failed_after_effect"
                and refreshed.output_hash is not None
            ),
            evidence={
                "effect_committed_event_count": self._event_count(run.run_id, "tool.effect_committed"),
                "completed_event_count": self._event_count(run.run_id, "tool.completed"),
                "output_hash": refreshed.output_hash,
            },
        )

    def _outbox_publish_failure(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        run = self.runtime.create_run(
            payload=AgentRunCreateRequest(
                project_id=project_id,
                intent="fault injection: outbox_publish_failure",
                auto_complete=True,
            ),
            current_user=current_user,
        )

        def fail_publish(event):
            raise RuntimeError(f"fault injection publish failed: {event.event_type}")

        summary = AgentOutboxPublisher(
            self.db,
            publisher=fail_publish,
            max_attempts=1,
        ).publish_pending(limit=20)
        dead_letters = len(list(self.db.scalars(
            select(AgentOutbox.id).where(AgentOutbox.status == "dead_letter")
        ).all()))
        event_count = self._event_count(run.run_id)
        return {
            "case_id": "outbox_publish_failure",
            "run_id": run.run_id,
            "tool_call_id": None,
            "passed": dead_letters >= 1 and event_count >= 1 and summary["dead_letter"] >= 1,
            "observed": {"outbox_dead_letter": dead_letters, "event_count": event_count},
            "evidence": {"publish_summary": summary},
        }

    def _reconcile_conflict(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        run, call = self._uncertain_call(project_id=project_id, current_user=current_user, effect_state="transport_sent_observed")
        result = ReconcileResult(
            found=True,
            status="conflict",
            backend_contract_version=call.backend_contract_version or "v1",
            error_code="idempotency_conflict",
            error_message="fault injection conflict",
        )
        summary = ReconcileWorker(self.db, router=_StaticReconcileRouter(result)).reconcile_run(
            run_id=run.run_id,
            current_user=current_user,
        )
        refreshed = self._get_call(call.tool_call_id)
        return self._result(
            case_id="reconcile_conflict",
            run=run,
            call=refreshed,
            passed=refreshed.status == "manual_intervention" and refreshed.recovery_decision == "idempotency_conflict",
            evidence={"reconcile_summary": summary},
        )

    def _unsupported_schema_version(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        run, call = self._uncertain_call(project_id=project_id, current_user=current_user, effect_state="transport_sent_observed")
        call.backend_contract_version = "unsupported-fault-contract"
        self.db.commit()
        summary = ReconcileWorker(self.db).reconcile_run(run_id=run.run_id, current_user=current_user)
        refreshed = self._get_call(call.tool_call_id)
        refreshed_run = self._get_run(run.run_id)
        return self._result(
            case_id="unsupported_schema_version",
            run=refreshed_run,
            call=refreshed,
            passed=refreshed.status == "needs_migration" and refreshed_run.status == "migration_blocked" and refreshed_run.migration_block_count >= 1,
            evidence={"reconcile_summary": summary, "migration_block_count": refreshed_run.migration_block_count},
        )

    def _migration_block_resolve_checkpoint_continue(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        run, blocked_call = self._uncertain_call(
            project_id=project_id,
            current_user=current_user,
            effect_state="transport_sent_observed",
        )
        completed_call = self.ledger.create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": project_id, "completed_before_migration": True},
                step_index=1,
            ),
            current_user=current_user,
            enqueue=False,
        )
        completed_call.status = "succeeded"
        completed_call.effect_submission_state = "effect_committed"
        completed_call.recovery_decision = "already_completed_before_migration"
        completed_call.output_json_redacted = {"preserved": True}
        blocked_call.backend_contract_version = "unsupported-fault-contract"
        self.db.commit()

        reconcile_summary = ReconcileWorker(self.db).reconcile_run(run_id=run.run_id, current_user=current_user)
        block = self.db.scalar(
            select(AgentMigrationBlock).where(
                AgentMigrationBlock.run_id == run.run_id,
                AgentMigrationBlock.status == "open",
            )
        )
        if block is None:
            raise RuntimeError("fault injection migration block was not created")
        blocked_call.backend_contract_version = "v1"
        self.db.commit()
        resolved, freshness = MigrationCoordinator(self.db).resolve_block(
            run_id=run.run_id,
            block_id=block.block_id,
            current_user=current_user,
            resolution_note="fault injection adapter deployed",
        )
        refreshed_run = self._get_run(run.run_id)
        refreshed_blocked = self._get_call(blocked_call.tool_call_id)
        refreshed_completed = self._get_call(completed_call.tool_call_id)
        passed = (
            resolved.status == "resolved"
            and freshness["action"] == "continue_from_checkpoint"
            and refreshed_run.status == "running"
            and refreshed_run.migration_block_count == 0
            and refreshed_run.blocking_tool_call_ids_json == []
            and refreshed_blocked.status == "reconciling"
            and refreshed_blocked.recovery_decision == "migration_block_resolved_reconcile_required"
            and refreshed_completed.status == "succeeded"
        )
        return {
            "case_id": "migration_block_resolve_checkpoint_continue",
            "run_id": run.run_id,
            "tool_call_id": refreshed_blocked.tool_call_id,
            "passed": passed,
            "observed": {
                "run_status": refreshed_run.status,
                "freshness_result": freshness["result"],
                "freshness_action": freshness["action"],
                "migration_block_status": resolved.status,
                "migration_block_count": refreshed_run.migration_block_count,
                "blocking_tool_call_ids": refreshed_run.blocking_tool_call_ids_json,
                "blocked_tool_status": refreshed_blocked.status,
                "completed_tool_status": refreshed_completed.status,
            },
            "evidence": {
                "block_id": block.block_id,
                "reconcile_summary": reconcile_summary,
                "resolved_by": resolved.resolved_by,
            },
        }

    def _legacy_no_receipt_high_risk(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        run, call = self._uncertain_call(project_id=project_id, current_user=current_user, effect_state="transport_sent_observed")
        call.backend_effect_capability = "legacy_no_receipt"
        call.resolved_side_effect_class = "business_create"
        call.resolved_replay_policy = "never_replay"
        self.db.commit()
        summary = ReconcileWorker(self.db).reconcile_run(run_id=run.run_id, current_user=current_user)
        refreshed = self._get_call(call.tool_call_id)
        return self._result(
            case_id="legacy_no_receipt_high_risk",
            run=run,
            call=refreshed,
            passed=refreshed.status == "manual_intervention" and refreshed.recovery_decision == "legacy_no_receipt_high_risk_manual",
            evidence={"reconcile_summary": summary},
        )

    def _approval_epoch_conflict(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        run = self.runtime.create_run(
            payload=AgentRunCreateRequest(project_id=project_id, intent="fault injection: approval_epoch_conflict"),
            current_user=current_user,
        )
        call = self.ledger.create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": project_id},
                step_index=0,
            ),
            current_user=current_user,
            enqueue=False,
        )
        call.resolved_side_effect_class = "business_create"
        call.approval_required = True
        approval = ApprovalService(self.db).create_pending_approval(
            call=call,
            run=run,
            current_user=current_user,
            reason="fault injection pending approval",
        )
        payload = AgentApprovalDecisionRequest(
            input_hash=approval.input_hash,
            runtime_snapshot_id=approval.runtime_snapshot_id,
            resource_scope_hash=approval.resource_scope_hash,
            approval_lineage_id=approval.approval_lineage_id,
            approval_epoch=approval.approval_epoch + 1,
            reason="fault injection stale epoch",
        )
        error_code = None
        try:
            ApprovalService(self.db).approve(tool_call_id=call.tool_call_id, payload=payload, current_user=current_user)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            error_code = str(detail.get("code") or exc.detail)
        conflict_events = self._event_count(run.run_id, "approval.approve_conflict")
        refreshed = self._get_call(call.tool_call_id)
        return self._result(
            case_id="approval_epoch_conflict",
            run=run,
            call=refreshed,
            passed=error_code == "approval_epoch_conflict" and conflict_events >= 1,
            evidence={"error_code": error_code, "approval_conflict_event_count": conflict_events},
        )

    def _approval_supersede_replacement_atomic(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        run = self.runtime.create_run(
            payload=AgentRunCreateRequest(project_id=project_id, intent="fault injection: approval_supersede_replacement_atomic"),
            current_user=current_user,
        )
        old_call = self.ledger.create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": project_id, "original": True},
                step_index=0,
            ),
            current_user=current_user,
            enqueue=False,
        )
        old_call.resolved_side_effect_class = "business_create"
        old_call.approval_required = True
        old_approval = ApprovalService(self.db).create_pending_approval(
            call=old_call,
            run=run,
            current_user=current_user,
            reason="fault injection original approval",
        )
        replacement_payload = AgentToolCallCreateRequest(
            run_id=run.run_id,
            tool_name="project.read_context",
            input={"project_id": project_id, "replacement": True},
            step_index=0,
        )
        superseded, lineage, replacement_call, replacement_approval, _, _ = (
            ApprovalService(self.db).supersede_with_replacement(
                tool_call_id=old_call.tool_call_id,
                replacement_payload=replacement_payload,
                current_user=current_user,
                reason="fault injection replacement",
            )
        )
        stale_error = None
        try:
            ApprovalService(self.db).approve(
                tool_call_id=old_call.tool_call_id,
                payload=AgentApprovalDecisionRequest(
                    input_hash=old_approval.input_hash,
                    runtime_snapshot_id=old_approval.runtime_snapshot_id,
                    resource_scope_hash=old_approval.resource_scope_hash,
                    approval_lineage_id=old_approval.approval_lineage_id,
                    approval_epoch=old_approval.approval_epoch,
                    reason="fault injection stale approve",
                ),
                current_user=current_user,
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            stale_error = str(detail.get("code") or exc.detail)
        events = {
            item.event_type
            for item in self.db.scalars(select(AgentEvent).where(AgentEvent.run_id == run.run_id)).all()
        }
        passed = (
            superseded.approval_status == "superseded"
            and lineage.current_epoch == replacement_approval.approval_epoch
            and lineage.tool_call_id == replacement_call.tool_call_id
            and replacement_approval.approval_status == "pending"
            and replacement_call.approval_epoch == replacement_approval.approval_epoch
            and stale_error == "approval_stale_or_superseded"
            and {"approval.superseded", "approval.created"}.issubset(events)
        )
        return {
            "case_id": "approval_supersede_replacement_atomic",
            "run_id": run.run_id,
            "tool_call_id": replacement_call.tool_call_id,
            "passed": passed,
            "observed": {
                "old_approval_status": superseded.approval_status,
                "replacement_approval_status": replacement_approval.approval_status,
                "lineage_epoch": lineage.current_epoch,
                "lineage_tool_call_id": lineage.tool_call_id,
                "stale_approve_error": stale_error,
            },
            "evidence": {
                "old_tool_call_id": old_call.tool_call_id,
                "replacement_tool_call_id": replacement_call.tool_call_id,
                "events": sorted(events),
            },
        }

    def _approval_expired_before_approve(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        run = self.runtime.create_run(
            payload=AgentRunCreateRequest(project_id=project_id, intent="fault injection: approval_expired_before_approve"),
            current_user=current_user,
        )
        call = self.ledger.create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": project_id},
                step_index=0,
            ),
            current_user=current_user,
            enqueue=False,
        )
        call.resolved_side_effect_class = "business_create"
        call.approval_required = True
        approval = ApprovalService(self.db).create_pending_approval(
            call=call,
            run=run,
            current_user=current_user,
            expires_at=_utcnow() - timedelta(seconds=1),
            reason="fault injection expiring approval",
        )
        expired = ApprovalExpireScanner(self.db).expire_due(now=_utcnow())
        refreshed = self._get_call(call.tool_call_id)
        self.db.refresh(approval)
        return self._result(
            case_id="approval_expired_before_approve",
            run=run,
            call=refreshed,
            passed=expired >= 1 and approval.approval_status == "expired" and refreshed.status == "manual_intervention",
            evidence={"expired_count": expired, "approval_status": approval.approval_status},
        )

    def _checkpoint_stale(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        run = self.runtime.create_run(
            payload=AgentRunCreateRequest(project_id=project_id, intent="fault injection: checkpoint_stale"),
            current_user=current_user,
        )
        checkpoint = self.db.get(AgentCheckpoint, run.last_checkpoint_id)
        if checkpoint is not None:
            checkpoint.created_at = _utcnow() - timedelta(hours=8)
            self.db.commit()
        freshness = CheckpointFreshnessGate(self.db, max_checkpoint_age_seconds=60).evaluate(run=run)
        self.runtime.append_event(run, "fault_injection.checkpoint_freshness_checked", freshness, commit=True)
        return {
            "case_id": "checkpoint_stale",
            "run_id": run.run_id,
            "tool_call_id": None,
            "passed": freshness["result"] == "too_old" and freshness["action"] == "replan_from_latest_safe_state",
            "observed": {"freshness_result": freshness["result"], "freshness_action": freshness["action"]},
            "evidence": {"checkpoint_freshness": freshness},
        }

    def _context_heavy_evidence_incomplete(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        run = self.runtime.create_run(
            payload=AgentRunCreateRequest(project_id=project_id, intent="fault injection: context_heavy_evidence_incomplete"),
            current_user=current_user,
        )
        evidence_refs = [
            {
                "evidence_ref_id": f"fault-evidence-{index}",
                "ref_type": "testcase",
                "ref_id": f"case-{index}",
                "mutability_class": "mutable_current",
                "dependency_role": "decision_dependency",
                "active_for_policy": True,
                "required_for_high_risk": index == 7,
                "content": "x" * 500,
            }
            for index in range(8)
        ]
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=128,
                evidence_refs=evidence_refs,
                required_evidence_ref_ids=["fault-evidence-7"],
            ),
            current_user=current_user,
        )
        observation = LoopController(self.db).record_observation(
            run_id=run.run_id,
            payload=AgentLoopObservationCreateRequest(
                decision_context_build_id=build.context_build_id,
                next_action="repair",
                next_action_is_high_risk=True,
                reasons=[],
                observation={"fault_case": "context_heavy_evidence_incomplete"},
            ),
            current_user=current_user,
        )
        return {
            "case_id": "context_heavy_evidence_incomplete",
            "run_id": run.run_id,
            "tool_call_id": None,
            "passed": (
                not build.required_evidence_complete
                and observation.root_cause_rule_id == "RC_CONTEXT_OMITTED_HIGH_RISK"
            ),
            "observed": {
                "required_evidence_complete": build.required_evidence_complete,
                "context_degradation_level": build.context_degradation_level,
                "root_cause_rule_id": observation.root_cause_rule_id,
            },
            "evidence": {"context_build_id": build.context_build_id, "observation_id": observation.observation_id},
        }

    def _loop_observation_decision_context_binding(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        run = self.runtime.create_run(
            payload=AgentRunCreateRequest(
                project_id=project_id,
                intent="fault injection: loop_observation_decision_context_binding",
            ),
            current_user=current_user,
        )
        plan_build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="plan",
                step_index=0,
                token_budget=1024,
                evidence_refs=[
                    {
                        "evidence_ref_id": "fault-plan-evidence",
                        "ref_type": "scenario",
                        "ref_id": "scenario-plan",
                        "mutability_class": "immutable",
                        "dependency_role": "trace",
                        "active_for_policy": False,
                    }
                ],
            ),
            current_user=current_user,
        )
        decision_build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=128,
                evidence_refs=[
                    {
                        "evidence_ref_id": f"fault-decision-evidence-{index}",
                        "ref_type": "testcase",
                        "ref_id": f"case-{index}",
                        "mutability_class": "mutable_current",
                        "dependency_role": "decision_dependency",
                        "active_for_policy": True,
                        "required_for_high_risk": index == 7,
                        "content": "x" * 500,
                    }
                    for index in range(8)
                ],
                required_evidence_ref_ids=["fault-decision-evidence-7"],
            ),
            current_user=current_user,
        )
        observation = LoopController(self.db).record_observation(
            run_id=run.run_id,
            payload=AgentLoopObservationCreateRequest(
                decision_context_build_id=decision_build.context_build_id,
                next_action="execute_tool",
                next_action_is_high_risk=True,
                reasons=["same_failure_no_progress"],
                observation={"fault_case": "loop_observation_decision_context_binding"},
            ),
            current_user=current_user,
        )
        passed = (
            observation.decision_context_build_id == decision_build.context_build_id
            and observation.decision_context_build_id != plan_build.context_build_id
            and observation.root_cause_rule_id == "RC_CONTEXT_OMITTED_HIGH_RISK"
            and not decision_build.required_evidence_complete
        )
        return {
            "case_id": "loop_observation_decision_context_binding",
            "run_id": run.run_id,
            "tool_call_id": None,
            "passed": passed,
            "observed": {
                "plan_context_build_id": plan_build.context_build_id,
                "decision_context_build_id": decision_build.context_build_id,
                "observation_context_build_id": observation.decision_context_build_id,
                "bound_to_latest_decision_build": observation.decision_context_build_id == decision_build.context_build_id,
                "root_cause_rule_id": observation.root_cause_rule_id,
            },
            "evidence": {
                "context_build_ids": [plan_build.context_build_id, decision_build.context_build_id],
                "observation_id": observation.observation_id,
                "required_evidence_complete": decision_build.required_evidence_complete,
            },
        }

    def _memory_contradiction(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        memory = MemoryManager(self.db).create_memory(
            project_id=project_id,
            memory_type="project_rule",
            title="Fault memory contradiction",
            content="Use the old behavior.",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[],
            current_user=current_user,
        )
        MemoryManager(self.db).record_contradiction(
            memory_id=memory.id,
            contradiction_type="execution_mismatch",
            severity="critical",
            current_user=current_user,
            failure_fingerprint="fault-memory-contradiction",
        )
        refreshed = self.db.get(ProjectMemory, memory.id)
        passed = refreshed is not None and refreshed.status == "needs_revalidation" and refreshed.contradiction_count == 1
        return {
            "case_id": "memory_contradiction",
            "run_id": "",
            "tool_call_id": None,
            "passed": passed,
            "observed": {
                "memory_status": refreshed.status if refreshed else None,
                "contradiction_count": refreshed.contradiction_count if refreshed else None,
            },
            "evidence": {"memory_id": memory.id},
        }

    def _evidence_historical_volatile_excluded(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        run = self.runtime.create_run(
            payload=AgentRunCreateRequest(project_id=project_id, intent="fault injection: evidence_historical_volatile_excluded"),
            current_user=current_user,
        )
        call = self.ledger.create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": project_id},
                step_index=0,
                evidence_refs=[
                    {
                        "evidence_ref_id": "fault-audit-latest",
                        "ref_type": "latest_execution_sample",
                        "ref_id": "latest",
                        "mutability_class": "ephemeral_latest",
                        "dependency_role": "audit_background",
                        "active_for_policy": False,
                    },
                    {
                        "evidence_ref_id": "fault-frozen-project",
                        "ref_type": "project",
                        "ref_id": str(project_id),
                        "mutability_class": "versioned",
                        "version_id": "v1",
                        "dependency_role": "decision_dependency",
                        "active_for_policy": True,
                    },
                ],
            ),
            current_user=current_user,
            enqueue=False,
        )
        reason = call.policy_reason_json or {}
        return self._result(
            case_id="evidence_historical_volatile_excluded",
            run=run,
            call=call,
            passed=(
                call.resolved_replay_policy == "reuse_allowed"
                and reason.get("historical_volatile_excluded_count") == 1
                and reason.get("volatile_policy_ref_count") == 0
                and len(call.policy_evidence_refs_json or []) == 1
                and len(call.audit_evidence_refs_json or []) == 1
            ),
            evidence={"policy_reason": reason},
        )

    def _evidence_mixed_volatile_frozen_requires_revalidation(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        run = self.runtime.create_run(
            payload=AgentRunCreateRequest(project_id=project_id, intent="fault injection: evidence_mixed_volatile_frozen_requires_revalidation"),
            current_user=current_user,
        )
        call = self.ledger.create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": project_id},
                step_index=0,
                evidence_refs=[
                    {
                        "evidence_ref_id": "fault-active-latest",
                        "ref_type": "latest_execution_sample",
                        "ref_id": "latest",
                        "mutability_class": "ephemeral_latest",
                        "dependency_role": "decision_dependency",
                        "active_for_policy": True,
                    },
                    {
                        "evidence_ref_id": "fault-active-frozen",
                        "ref_type": "execution_record",
                        "ref_id": "exec-1",
                        "mutability_class": "immutable",
                        "content_hash": "hash-exec-1",
                        "dependency_role": "validation_evidence",
                        "active_for_policy": True,
                    },
                ],
            ),
            current_user=current_user,
            enqueue=False,
        )
        reason = call.policy_reason_json or {}
        return self._result(
            case_id="evidence_mixed_volatile_frozen_requires_revalidation",
            run=run,
            call=call,
            passed=(
                call.resolved_replay_policy == "require_revalidation"
                and reason.get("volatile_policy_ref_count") == 1
                and reason.get("frozen_policy_ref_count") == 1
                and reason.get("mixed_volatile_frozen") is True
            ),
            evidence={"policy_reason": reason},
        )

    def _memory_stale_evidence_watch(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        memory = MemoryManager(self.db).create_memory(
            project_id=project_id,
            memory_type="project_rule",
            title="Fault memory stale",
            content="Depends on environment.",
            source_type="document_imported",
            source_ref_json={"document_id": "fault-doc", "content_hash": "hash-fault-doc"},
            evidence_refs=[
                {
                    "evidence_ref_id": "fault-env",
                    "ref_type": "environment",
                    "ref_id": "env-1",
                    "mutability_class": "mutable_current",
                    "dependency_role": "policy_dependency",
                    "active_for_policy": True,
                }
            ],
            current_user=current_user,
        )
        touched = MemoryStalenessWorker(self.db).mark_memories_stale_for_ref(
            evidence_ref_type="environment",
            evidence_ref_id="env-1",
            stale_reason="environment.updated",
        )
        refreshed = self.db.get(ProjectMemory, memory.id)
        passed = touched == 1 and refreshed is not None and refreshed.status == "needs_revalidation"
        return {
            "case_id": "memory_stale_evidence_watch",
            "run_id": "",
            "tool_call_id": None,
            "passed": passed,
            "observed": {
                "touched": touched,
                "memory_status": refreshed.status if refreshed else None,
                "stale_score": refreshed.stale_score if refreshed else None,
            },
            "evidence": {"memory_id": memory.id},
        }

    def _memory_bypassed_evidence_ref(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        run = self.runtime.create_run(
            payload=AgentRunCreateRequest(project_id=project_id, intent="fault injection: memory_bypassed_evidence_ref"),
            current_user=current_user,
        )
        memory = MemoryManager(self.db).create_memory(
            project_id=project_id,
            memory_type="project_rule",
            title="Fault bypassed memory",
            content="This memory must be wrapped before prompt use.",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[],
            current_user=current_user,
        )
        error_code = None
        try:
            ContextBuilder(self.db).build(
                run_id=run.run_id,
                payload=AgentContextBuildCreateRequest(
                    build_purpose="repair",
                    step_index=0,
                    token_budget=4000,
                    memory_ids_used=[memory.id],
                    evidence_refs=[],
                ),
                current_user=current_user,
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            error_code = str(detail.get("code") or exc.detail)
        bypass_events = self._event_count(run.run_id, "memory.bypassed_evidence_ref")
        return {
            "case_id": "memory_bypassed_evidence_ref",
            "run_id": run.run_id,
            "tool_call_id": None,
            "passed": error_code == "memory_bypassed_evidence_ref" and bypass_events == 1,
            "observed": {"error_code": error_code, "event_count": bypass_events},
            "evidence": {"memory_id": memory.id, "bypass_event_count": bypass_events},
        }

    def _duplicate_idempotency_key(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        run = self.runtime.create_run(
            payload=AgentRunCreateRequest(project_id=project_id, intent="fault injection: duplicate_idempotency_key"),
            current_user=current_user,
        )
        payload = AgentToolCallCreateRequest(
            run_id=run.run_id,
            tool_name="project.read_context",
            input={"project_id": project_id},
            step_index=0,
            idempotency_key="fault-duplicate-key",
        )
        first = self.ledger.create_tool_call(payload=payload, current_user=current_user, enqueue=False)
        second = self.ledger.create_tool_call(payload=payload, current_user=current_user, enqueue=False)
        duplicate_events = self._event_count(run.run_id, "tool.duplicate_blocked")
        refreshed = self._get_call(first.tool_call_id)
        return self._result(
            case_id="duplicate_idempotency_key",
            run=run,
            call=refreshed,
            passed=first.tool_call_id == second.tool_call_id and duplicate_events == 1,
            evidence={"duplicate_event_count": duplicate_events, "reused_tool_call_id": second.tool_call_id},
        )

    def _permission_revoked_before_execution(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        revoked_user = self._create_fault_member(project_id=project_id, current_user=current_user)
        run = self.runtime.create_run(
            payload=AgentRunCreateRequest(project_id=project_id, intent="fault injection: permission_revoked_before_execution"),
            current_user=revoked_user,
        )
        call = self.ledger.create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="report.read_summary",
                input={"project_id": project_id},
                step_index=0,
            ),
            current_user=revoked_user,
            enqueue=True,
        )
        permissions = list(
            self.db.scalars(
                select(ProjectMemberPermission)
                .join(ProjectMember)
                .where(ProjectMember.project_id == project_id, ProjectMember.user_id == revoked_user.id)
            ).all()
        )
        for permission in permissions:
            self.db.delete(permission)
        self.db.commit()
        refreshed = ToolExecutor(self.db).execute_next(worker_id="fault-injection-permission")
        if refreshed is None:
            refreshed = self._get_call(call.tool_call_id)
        failed_events = self._event_count(run.run_id, "tool.failed")
        return self._result(
            case_id="permission_revoked_before_execution",
            run=run,
            call=refreshed,
            passed=(
                refreshed.status == "failed"
                and refreshed.error_code == "permission_revoked_before_execution"
                and failed_events >= 1
            ),
            evidence={"tool_failed_event_count": failed_events, "revoked_user_id": revoked_user.id},
        )

    def _worker_queue_reconcile_required(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        evidence: list[dict[str, Any]] = []
        for call_status in ("uncertain", "reconciling"):
            run, call = self._uncertain_call(
                project_id=project_id,
                current_user=current_user,
                effect_state="transport_sent_observed",
            )
            call.status = call_status
            self.db.commit()
            queue_item = AgentWorkerQueueService(self.db).enqueue_tool_call(call)
            ToolExecutor(self.db).execute_next(worker_id=f"fault-injection-{call_status}")
            refreshed = self._get_call(call.tool_call_id)
            self.db.refresh(queue_item)
            evidence.append({
                "run_id": run.run_id,
                "tool_call_id": refreshed.tool_call_id,
                "seeded_status": call_status,
                "tool_status": refreshed.status,
                "queue_status": queue_item.status,
                "tool_error_code": refreshed.error_code,
                "queue_error_code": queue_item.last_error_code,
                "recovery_decision": refreshed.recovery_decision,
            })

        passed = all(
            item["tool_status"] == item["seeded_status"]
            and item["queue_status"] == "failed"
            and item["tool_error_code"] == "tool_call_uncertain_reconcile_required"
            and item["queue_error_code"] == "tool_call_uncertain_reconcile_required"
            and item["recovery_decision"] == "reconcile_required_before_execution"
            for item in evidence
        )
        return {
            "case_id": "worker_queue_reconcile_required",
            "run_id": evidence[0]["run_id"],
            "tool_call_id": evidence[0]["tool_call_id"],
            "passed": passed,
            "observed": {
                "blocked_statuses": [item["seeded_status"] for item in evidence],
                "queue_statuses": [item["queue_status"] for item in evidence],
                "error_code": "tool_call_uncertain_reconcile_required",
                "recovery_decision": "reconcile_required_before_execution",
            },
            "evidence": {"blocked_tool_calls": evidence},
        }

    def _root_cause_rule_missing(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        run = self.runtime.create_run(
            payload=AgentRunCreateRequest(project_id=project_id, intent="fault injection: root_cause_rule_missing"),
            current_user=current_user,
        )
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(build_purpose="repair", step_index=0),
            current_user=current_user,
        )
        observation = LoopController(self.db).record_observation(
            run_id=run.run_id,
            payload=AgentLoopObservationCreateRequest(
                decision_context_build_id=build.context_build_id,
                next_action="repair",
                reasons=["unclassified_fault_injection_reason"],
                observation={"fault_case": "root_cause_rule_missing"},
            ),
            current_user=current_user,
        )
        passed = (
            observation.root_cause_rule_id == "RC_RULE_MISSING"
            and observation.root_cause_primary == "root_cause_rule_missing"
        )
        return {
            "case_id": "root_cause_rule_missing",
            "run_id": run.run_id,
            "tool_call_id": None,
            "passed": passed,
            "observed": {
                "root_cause_rule_id": observation.root_cause_rule_id,
                "root_cause_primary": observation.root_cause_primary,
                "mitigation_action": observation.mitigation_action,
            },
            "evidence": {"observation_id": observation.observation_id, "context_build_id": build.context_build_id},
        }

    def _high_risk_memory_only_blocked(self, *, project_id: int, current_user: User) -> dict[str, Any]:
        run = self.runtime.create_run(
            payload=AgentRunCreateRequest(project_id=project_id, intent="fault injection: high_risk_memory_only_blocked"),
            current_user=current_user,
        )
        memory_ref = {
            "evidence_ref_id": "memory:fault:v1",
            "ref_type": "memory",
            "ref_id": "fault",
            "mutability_class": "mutable_current",
            "dependency_role": "policy_dependency",
            "active_for_policy": True,
            "authority": "memory:user_confirmed",
        }
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                evidence_refs=[memory_ref],
                required_evidence_ref_ids=["memory:fault:v1"],
            ),
            current_user=current_user,
        )
        call = self.ledger.create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": project_id},
                evidence_refs=[memory_ref],
                step_index=0,
                decision_context_build_id=build.context_build_id,
            ),
            current_user=current_user,
            enqueue=False,
        )
        call.resolved_side_effect_class = "business_create"
        self.db.commit()
        AgentWorkerQueueService(self.db).enqueue_tool_call(call)
        refreshed = ToolExecutor(self.db).execute_next(worker_id="fault-injection-memory")
        if refreshed is None:
            refreshed = self._get_call(call.tool_call_id)
        return self._result(
            case_id="high_risk_memory_only_blocked",
            run=run,
            call=refreshed,
            passed=(
                refreshed.status == "manual_intervention"
                and refreshed.error_code == "high_risk_action_cannot_depend_only_on_memory"
            ),
            evidence={"context_build_id": build.context_build_id},
        )

    def _uncertain_call(self, *, project_id: int, current_user: User, effect_state: str) -> tuple[AgentRun, AgentToolCall]:
        run = self.runtime.create_run(
            payload=AgentRunCreateRequest(project_id=project_id, intent=f"fault injection: {effect_state}"),
            current_user=current_user,
        )
        call = self.ledger.create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": project_id},
                step_index=0,
            ),
            current_user=current_user,
            enqueue=False,
        )
        call.status = "uncertain"
        call.effect_submission_state = effect_state
        call.output_json_redacted = None
        call.output_hash = None
        call.recovery_decision = "fault_injection_seeded"
        self.runtime.append_event(
            run,
            "fault_injection.seeded",
            {"case_effect_state": effect_state, "tool_call_id": call.tool_call_id},
            commit=False,
        )
        self.db.commit()
        return run, call

    def _result(
        self,
        *,
        case_id: str,
        run: AgentRun,
        call: AgentToolCall,
        passed: bool,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        result = {
            "case_id": case_id,
            "run_id": run.run_id,
            "tool_call_id": call.tool_call_id,
            "passed": passed,
            "observed": {
                "run_status": run.status,
                "tool_status": call.status,
                "effect_submission_state": call.effect_submission_state,
                "recovery_decision": call.recovery_decision,
                "error_code": call.error_code,
            },
            "evidence": evidence,
        }
        return self._result_item(result)

    @staticmethod
    def _result_item(result: dict[str, Any]) -> dict[str, Any]:
        item = {**result, "tool_call_id": result.get("tool_call_id")}
        return {field: item[field] for field in FAULT_INJECTION_RESULT_FIELDS}

    def _get_call(self, tool_call_id: str) -> AgentToolCall:
        call = self.db.scalar(select(AgentToolCall).where(AgentToolCall.tool_call_id == tool_call_id))
        if call is None:
            raise RuntimeError(f"fault injection call disappeared: {tool_call_id}")
        return call

    def _get_run(self, run_id: str) -> AgentRun:
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == run_id))
        if run is None:
            raise RuntimeError(f"fault injection run disappeared: {run_id}")
        return run

    def _event_count(self, run_id: str, event_type: str | None = None) -> int:
        statement = select(AgentEvent.id).where(AgentEvent.run_id == run_id)
        if event_type is not None:
            statement = statement.where(AgentEvent.event_type == event_type)
        return len(list(self.db.scalars(statement).all()))

    def _reconcile_attempt_count(self, tool_call_id: str) -> int:
        from app.models.agent import AgentReconcileAttempt

        return len(list(self.db.scalars(select(AgentReconcileAttempt.id).where(AgentReconcileAttempt.tool_call_id == tool_call_id)).all()))

    def _create_fault_member(self, *, project_id: int, current_user: User) -> User:
        max_user_id = self.db.scalar(select(User.id).order_by(User.id.desc()).limit(1)) or 0
        next_user_id = max_user_id + 1
        user = User(
            id=next_user_id,
            username=f"fault-member-{next_user_id}",
            account=f"fault-member-{next_user_id}",
            password_hash="fault",
            phone=f"199{next_user_id:08d}"[-11:],
            email=f"fault-member-{next_user_id}@example.test",
            is_admin=False,
        )
        self.db.add(user)
        self.db.flush()
        member = ProjectMember(project_id=project_id, user_id=user.id, added_by_id=current_user.id, is_active=True)
        self.db.add(member)
        self.db.flush()
        self.db.add(
            ProjectMemberPermission(
                member_id=member.id,
                permission_code=ProjectPermission.VIEW_REPORT.value,
            )
        )
        self.db.commit()
        self.db.refresh(user)
        return user


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class _StaticReconcileRouter:
    def __init__(self, result: ReconcileResult):
        self.result = result

    def reconcile(self, **kwargs):
        _ = kwargs
        return self.result


class _EventStoreFailingRuntime:
    def __init__(self, db: Session):
        self.inner = AgentRuntimeService(db)

    def append_event(self, run: AgentRun, event_type: str, payload: dict[str, Any], *, commit: bool = True) -> AgentEvent:
        if event_type == "tool.effect_committed":
            raise RuntimeError("fault injection eventstore write failed after backend success")
        return self.inner.append_event(run, event_type, payload, commit=commit)
