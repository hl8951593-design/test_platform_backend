from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import AgentCheckpoint, AgentEvent, AgentRun, AgentToolCall
from app.models.user import User
from app.schemas.agent import AgentApprovalDecisionRequest, AgentRunCreateRequest, AgentToolCallCreateRequest
from app.services.agent_approval_service import ApprovalService
from app.services.agent_reconcile_service import CheckpointFreshnessGate, ReconcileWorker
from app.services.agent_runtime_service import AgentRuntimeService, ExecutionLedgerService


FAULT_CASES = (
    "send_intent_not_found",
    "transport_sent_not_found",
    "unsupported_schema_version",
    "legacy_no_receipt_high_risk",
    "approval_epoch_conflict",
    "checkpoint_stale",
)


class AgentFaultInjectionService:
    def __init__(self, db: Session):
        self.db = db
        self.runtime = AgentRuntimeService(db)
        self.ledger = ExecutionLedgerService(db)

    def list_cases(self) -> list[dict[str, Any]]:
        return [
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
                "case_id": "unsupported_schema_version",
                "description": "Validate unsupported backend contract creates an open migration block and blocks the run.",
                "expected": {"tool_status": "needs_migration", "run_status": "migration_blocked"},
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
                "case_id": "checkpoint_stale",
                "description": "Validate stale checkpoints require replan rather than direct resume.",
                "expected": {"freshness_result": "too_old", "freshness_action": "replan_from_latest_safe_state"},
            },
        ]

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
        results = [self._run_case(case_id=case_id, project_id=project_id, current_user=current_user) for case_id in requested]
        return {
            "project_id": project_id,
            "requested": len(requested),
            "passed": sum(1 for item in results if item["passed"]),
            "failed": sum(1 for item in results if not item["passed"]),
            "results": results,
        }

    def _run_case(self, *, case_id: str, project_id: int, current_user: User) -> dict[str, Any]:
        handlers = {
            "send_intent_not_found": self._send_intent_not_found,
            "transport_sent_not_found": self._transport_sent_not_found,
            "unsupported_schema_version": self._unsupported_schema_version,
            "legacy_no_receipt_high_risk": self._legacy_no_receipt_high_risk,
            "approval_epoch_conflict": self._approval_epoch_conflict,
            "checkpoint_stale": self._checkpoint_stale,
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
            passed=refreshed.status == "uncertain" and refreshed.recovery_decision == "reconcile_backoff" and attempts >= 1,
            evidence={"reconcile_summary": summary, "reconcile_attempt_count": attempts},
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
        return {
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

    def _event_count(self, run_id: str, event_type: str) -> int:
        return len(list(self.db.scalars(select(AgentEvent.id).where(AgentEvent.run_id == run_id, AgentEvent.event_type == event_type)).all()))

    def _reconcile_attempt_count(self, tool_call_id: str) -> int:
        from app.models.agent import AgentReconcileAttempt

        return len(list(self.db.scalars(select(AgentReconcileAttempt.id).where(AgentReconcileAttempt.tool_call_id == tool_call_id)).all()))


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
