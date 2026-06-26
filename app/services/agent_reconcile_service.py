from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.sensitive_data import mask_sensitive, request_fingerprint
from app.models.agent import (
    AgentBackendContract,
    AgentCheckpoint,
    AgentEvidenceWatch,
    AgentMigrationBlock,
    AgentApproval,
    AgentReconcileAttempt,
    AgentRun,
    AgentToolCall,
)
from app.models.user import User
from app.schemas.agent import ReconcileResult
from app.services.agent_runtime_service import AgentRuntimeService, RUN_TERMINAL_STATUSES
from app.services.agent_tool_service import SAFE_SIDE_EFFECT_CLASSES
from app.services.permission_service import PermissionService


RECONCILE_ELIGIBLE_STATUSES = {"uncertain", "reconciling"}


class BackendContractRegistry:
    def __init__(self, db: Session):
        self.db = db

    def get_for_call(self, call: AgentToolCall) -> AgentBackendContract:
        if not call.backend_name or not call.backend_operation or not call.backend_contract_version:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "backend_contract_unsupported"},
            )
        contract = self.db.scalar(
            select(AgentBackendContract).where(
                AgentBackendContract.backend_name == call.backend_name,
                AgentBackendContract.backend_operation == call.backend_operation,
                AgentBackendContract.backend_contract_version == call.backend_contract_version,
            )
        )
        if contract is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "backend_contract_unsupported"},
            )
        return contract


class ReconcileAdapter(Protocol):
    def reconcile(self, *, call: AgentToolCall, contract: AgentBackendContract) -> ReconcileResult:
        ...


class LedgerOutputReconcileAdapter:
    def reconcile(self, *, call: AgentToolCall, contract: AgentBackendContract) -> ReconcileResult:
        if call.output_json_redacted is None:
            return ReconcileResult(
                found=False,
                status="not_found",
                backend_contract_version=contract.backend_contract_version,
                output_schema_version=contract.output_schema_hash,
                error_code="reconcile_not_found",
                error_message="No downstream idempotency record is available for this initial adapter.",
            )
        return ReconcileResult(
            found=True,
            status="succeeded",
            backend_contract_version=contract.backend_contract_version,
            output_schema_version=contract.output_schema_hash,
            external_resource_type=call.external_resource_type or f"{call.backend_name}:{call.backend_operation}",
            external_resource_id=call.external_resource_id or call.tool_call_id,
            acceptance_id=call.downstream_acceptance_id,
            canonical_summary_json=call.output_json_redacted,
            raw_output_object_key=call.raw_output_object_key,
        )


class BackendReconcileRouter:
    def __init__(self, adapters: dict[tuple[str, str], ReconcileAdapter] | None = None):
        self.adapters = adapters or {
            ("project-service", "read_context"): LedgerOutputReconcileAdapter(),
            ("ai-skill-service", "run_draft"): LedgerOutputReconcileAdapter(),
            ("ai-skill-service", "scenario.compose_draft"): LedgerOutputReconcileAdapter(),
            ("scenario-service", "execute_dry_run"): LedgerOutputReconcileAdapter(),
            ("testcase-service", "validate_schema"): LedgerOutputReconcileAdapter(),
            ("report-service", "read_summary"): LedgerOutputReconcileAdapter(),
        }

    def reconcile(self, *, call: AgentToolCall, contract: AgentBackendContract) -> ReconcileResult:
        adapter = self.adapters.get((contract.backend_name, contract.backend_operation))
        if adapter is None:
            return ReconcileResult(
                found=False,
                status="unsupported_schema_version",
                schema_support="unsupported",
                backend_contract_version=contract.backend_contract_version,
                output_schema_version=contract.output_schema_hash,
                error_code="backend_reconcile_adapter_missing",
                error_message="No reconcile adapter is registered for this backend operation.",
            )
        return adapter.reconcile(call=call, contract=contract)


class MigrationCoordinator:
    def __init__(self, db: Session):
        self.db = db
        self.permission_service = PermissionService(db)

    def create_tool_call_block(
        self,
        *,
        run: AgentRun,
        call: AgentToolCall,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> AgentMigrationBlock:
        existing = self.db.scalar(
            select(AgentMigrationBlock).where(
                AgentMigrationBlock.run_id == run.run_id,
                AgentMigrationBlock.tool_call_id == call.tool_call_id,
                AgentMigrationBlock.status == "open",
            )
        )
        if existing is not None:
            self._refresh_run_block_state(run)
            return existing
        block = AgentMigrationBlock(
            block_id=f"agent-migration-{uuid.uuid4().hex}",
            run_id=run.run_id,
            tool_call_id=call.tool_call_id,
            status="open",
            block_type="tool_call",
            reason=reason,
            backend_name=call.backend_name,
            backend_operation=call.backend_operation,
            backend_contract_version=call.backend_contract_version,
            required_migration_type="backend_contract_adapter",
            details_json=mask_sensitive(details or {}),
        )
        self.db.add(block)
        self.db.flush()
        self._refresh_run_block_state(run)
        return block

    def _refresh_run_block_state(self, run: AgentRun) -> None:
        open_blocks = list(self.db.scalars(
            select(AgentMigrationBlock).where(
                AgentMigrationBlock.run_id == run.run_id,
                AgentMigrationBlock.status == "open",
            )
        ).all())
        run.migration_block_count = len(open_blocks)
        run.blocking_tool_call_ids_json = [
            item.tool_call_id for item in open_blocks if item.tool_call_id
        ]
        if open_blocks:
            run.status = "migration_blocked"

    def list_blocks(self, *, run_id: str, current_user: User) -> list[AgentMigrationBlock]:
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == run_id))
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
        self.permission_service.require_project_access(current_user, run.project_id)
        return list(
            self.db.scalars(
                select(AgentMigrationBlock)
                .where(AgentMigrationBlock.run_id == run_id)
                .order_by(AgentMigrationBlock.created_at.asc())
            ).all()
        )

    def resolve_block(
        self,
        *,
        run_id: str,
        block_id: str,
        current_user: User,
        resolution_note: str | None = None,
    ) -> tuple[AgentMigrationBlock, dict[str, Any]]:
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == run_id).with_for_update())
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
        self.permission_service.require_project_access(current_user, run.project_id)
        block = self.db.scalar(
            select(AgentMigrationBlock)
            .where(AgentMigrationBlock.run_id == run_id, AgentMigrationBlock.block_id == block_id)
            .with_for_update()
        )
        if block is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent migration block not found")
        if block.status == "resolved":
            return block, CheckpointFreshnessGate(self.db).evaluate(run=run)

        now = _utcnow()
        block.status = "resolved"
        block.resolved_at = now
        block.resolved_by = current_user.id
        block.resolution_summary_json = mask_sensitive({
            "resolution_note": resolution_note,
            "resolved_by": current_user.id,
            "resolved_at": now.isoformat(),
        })
        if block.tool_call_id:
            call = self.db.scalar(
                select(AgentToolCall).where(AgentToolCall.tool_call_id == block.tool_call_id).with_for_update()
            )
            if call is not None and call.status == "needs_migration":
                call.status = "reconciling"
                call.recovery_decision = "migration_block_resolved_reconcile_required"
                call.error_code = None
                call.error_message = None

        self._refresh_run_block_state_after_resolution(run)
        freshness = CheckpointFreshnessGate(self.db).evaluate(run=run)
        checkpoint = self.db.get(AgentCheckpoint, run.last_checkpoint_id) if run.last_checkpoint_id else None
        if checkpoint is not None:
            checkpoint.freshness_metadata_json = freshness
        if run.migration_block_count == 0:
            if freshness["action"] == "continue_from_checkpoint":
                run.status = "running"
                run.error_code = None
                run.error_message = None
            else:
                run.status = "paused"
                run.error_code = freshness["action"]
                run.error_message = freshness["reason"]

        runtime = AgentRuntimeService(self.db)
        runtime.append_event(
            run,
            "checkpoint.freshness_checked",
            {"block_id": block.block_id, **freshness},
            commit=False,
        )
        runtime.append_event(
            run,
            "run.migration_resolved",
            {"block_id": block.block_id, "run_status": run.status},
            commit=False,
        )
        self.db.commit()
        self.db.refresh(block)
        return block, freshness

    def _refresh_run_block_state_after_resolution(self, run: AgentRun) -> None:
        open_blocks = list(self.db.scalars(
            select(AgentMigrationBlock).where(
                AgentMigrationBlock.run_id == run.run_id,
                AgentMigrationBlock.status == "open",
            )
        ).all())
        run.migration_block_count = len(open_blocks)
        run.blocking_tool_call_ids_json = [item.tool_call_id for item in open_blocks if item.tool_call_id]
        if open_blocks:
            run.status = "migration_blocked"


class CheckpointFreshnessGate:
    def __init__(self, db: Session, *, max_checkpoint_age_seconds: int = 4 * 60 * 60):
        self.db = db
        self.max_checkpoint_age_seconds = max_checkpoint_age_seconds

    def evaluate(self, *, run: AgentRun) -> dict[str, Any]:
        now = _utcnow()
        checks: dict[str, Any] = {
            "checked_at": now.isoformat(),
            "run_id": run.run_id,
            "checkpoint_id": run.last_checkpoint_id,
            "checkpoint_age_seconds": None,
            "open_migration_block_count": 0,
            "stale_evidence_watch_count": 0,
            "pending_approval_count": 0,
            "backend_contract_missing_count": 0,
            "result": "fresh",
            "action": "continue_from_checkpoint",
            "reason": "fresh",
        }
        checkpoint = self.db.get(AgentCheckpoint, run.last_checkpoint_id) if run.last_checkpoint_id else None
        if checkpoint is None:
            checks.update(result="too_old", action="replan_from_latest_safe_state", reason="checkpoint_missing")
            return checks
        checks["checkpoint_age_seconds"] = int((now - checkpoint.created_at).total_seconds())
        if checks["checkpoint_age_seconds"] > self.max_checkpoint_age_seconds:
            checks.update(result="too_old", action="replan_from_latest_safe_state", reason="checkpoint_too_old")
            return checks

        open_blocks = self.db.scalar(
            select(func.count(AgentMigrationBlock.id)).where(
                AgentMigrationBlock.run_id == run.run_id,
                AgentMigrationBlock.status == "open",
            )
        ) or 0
        checks["open_migration_block_count"] = int(open_blocks)
        if open_blocks:
            checks.update(result="backend_contract_changed", action="migration_block", reason="open_migration_blocks")
            return checks

        stale_watches = self.db.scalar(
            select(func.count(AgentEvidenceWatch.id)).where(
                AgentEvidenceWatch.run_id == run.run_id,
                AgentEvidenceWatch.watch_status == "stale",
            )
        ) or 0
        checks["stale_evidence_watch_count"] = int(stale_watches)
        if stale_watches:
            checks.update(result="evidence_stale", action="fetch_evidence_and_rebuild_context", reason="stale_evidence_watch")
            return checks

        pending_approvals = self.db.scalar(
            select(func.count(AgentApproval.id)).where(
                AgentApproval.run_id == run.run_id,
                AgentApproval.approval_status == "pending",
            )
        ) or 0
        checks["pending_approval_count"] = int(pending_approvals)
        if pending_approvals:
            checks.update(result="approval_stale", action="supersede_or_refresh_approval", reason="pending_approval_after_wait")
            return checks

        calls = list(
            self.db.scalars(
                select(AgentToolCall).where(
                    AgentToolCall.run_id == run.run_id,
                    AgentToolCall.backend_name.is_not(None),
                    AgentToolCall.backend_operation.is_not(None),
                    AgentToolCall.backend_contract_version.is_not(None),
                )
            ).all()
        )
        missing_contracts = 0
        for call in calls:
            contract = self.db.scalar(
                select(AgentBackendContract.id).where(
                    AgentBackendContract.backend_name == call.backend_name,
                    AgentBackendContract.backend_operation == call.backend_operation,
                    AgentBackendContract.backend_contract_version == call.backend_contract_version,
                    AgentBackendContract.compatibility_status == "active",
                )
            )
            if contract is None:
                missing_contracts += 1
        checks["backend_contract_missing_count"] = missing_contracts
        if missing_contracts:
            checks.update(result="backend_contract_changed", action="migration_block", reason="backend_contract_missing")
            return checks

        return checks


class ReconcileWorker:
    def __init__(
        self,
        db: Session,
        *,
        router: BackendReconcileRouter | None = None,
        backoff_seconds: int = 30,
    ):
        self.db = db
        self.router = router or BackendReconcileRouter()
        self.backoff_seconds = backoff_seconds
        self.permission_service = PermissionService(db)
        self.contract_registry = BackendContractRegistry(db)
        self.migration_coordinator = MigrationCoordinator(db)

    def reconcile_run(self, *, run_id: str, current_user: User) -> dict[str, Any]:
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == run_id).with_for_update())
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run 不存在")
        self.permission_service.require_project_access(current_user, run.project_id)
        if run.status in RUN_TERMINAL_STATUSES:
            return self._summary(run_id, [])

        calls = list(self.db.scalars(
            select(AgentToolCall)
            .where(
                AgentToolCall.run_id == run_id,
                AgentToolCall.status.in_(RECONCILE_ELIGIBLE_STATUSES),
            )
            .order_by(AgentToolCall.step_index.asc(), AgentToolCall.attempt_index.asc())
        ).all())
        processed = [self.reconcile_tool_call(call=call, run=run) for call in calls]
        self.db.commit()
        return self._summary(run_id, processed)

    def reconcile_tool_call(self, *, call: AgentToolCall, run: AgentRun | None = None) -> AgentToolCall:
        run = run or self.db.scalar(select(AgentRun).where(AgentRun.run_id == call.run_id).with_for_update())
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run 不存在")
        call = self.db.scalar(select(AgentToolCall).where(AgentToolCall.id == call.id).with_for_update()) or call
        if call.status not in RECONCILE_ELIGIBLE_STATUSES:
            return call

        runtime = AgentRuntimeService(self.db)
        if call.backend_effect_capability == "legacy_no_receipt" and call.resolved_side_effect_class not in SAFE_SIDE_EFFECT_CLASSES:
            call.status = "manual_intervention"
            call.recovery_decision = "legacy_no_receipt_high_risk_manual"
            call.error_code = "backend_capability_too_weak"
            runtime.append_event(run, "tool.failed", {"tool_call_id": call.tool_call_id, "error_code": call.error_code}, commit=False)
            return call

        try:
            contract = self.contract_registry.get_for_call(call)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT:
                return self._mark_needs_migration(
                    run=run,
                    call=call,
                    result=ReconcileResult(
                        found=False,
                        status="unsupported_schema_version",
                        schema_support="adapter_required",
                        backend_contract_version=call.backend_contract_version or "unknown",
                        error_code="backend_contract_unsupported",
                        error_message="Backend contract is not registered.",
                    ),
                )
            raise

        call.status = "reconciling"
        result = self.router.reconcile(call=call, contract=contract)
        attempt = self._record_attempt(call=call, result=result)

        if result.status == "succeeded":
            call.status = "succeeded"
            call.effect_submission_state = "effect_committed"
            call.output_json_redacted = mask_sensitive(result.canonical_summary_json)
            call.output_hash = request_fingerprint(result.canonical_summary_json)
            call.raw_output_object_key = result.raw_output_object_key
            call.external_resource_type = result.external_resource_type
            call.external_resource_id = result.external_resource_id
            call.downstream_acceptance_id = result.acceptance_id or call.downstream_acceptance_id
            call.error_code = None
            call.error_message = None
            call.recovery_decision = "mark_succeeded_from_reconcile"
            runtime.append_event(
                run,
                "tool.reconciled",
                {"tool_call_id": call.tool_call_id, "status": result.status},
                commit=False,
            )
            return call
        if result.status == "running":
            call.status = "reconciling"
            call.recovery_decision = "still_running"
            attempt.next_retry_at = _utcnow() + timedelta(seconds=self.backoff_seconds)
            runtime.append_event(run, "tool.uncertain", {"tool_call_id": call.tool_call_id, "status": result.status}, commit=False)
            return call
        if result.status == "not_found":
            self._handle_not_found(run=run, call=call, attempt=attempt)
            return call
        if result.status == "conflict":
            call.status = "manual_intervention"
            call.recovery_decision = "idempotency_conflict"
            call.error_code = result.error_code or "idempotency_conflict"
            call.error_message = result.error_message
            runtime.append_event(run, "tool.failed", {"tool_call_id": call.tool_call_id, "error_code": call.error_code}, commit=False)
            return call
        if result.status == "failed":
            call.status = "failed"
            call.recovery_decision = "mark_failed_from_reconcile"
            call.error_code = result.error_code or "backend_reconcile_failed"
            call.error_message = result.error_message
            runtime.append_event(run, "tool.failed", {"tool_call_id": call.tool_call_id, "error_code": call.error_code}, commit=False)
            return call
        if result.status == "unsupported_schema_version":
            return self._mark_needs_migration(run=run, call=call, result=result, record_attempt=False)
        return call

    def _handle_not_found(self, *, run: AgentRun, call: AgentToolCall, attempt: AgentReconcileAttempt) -> None:
        runtime = AgentRuntimeService(self.db)
        state = call.effect_submission_state
        capability = call.backend_effect_capability
        if state == "send_intent_recorded":
            call.status = "failed_retryable"
            call.recovery_decision = "safe_retry_same_idempotency_key"
            attempt.next_retry_at = _utcnow()
            runtime.append_event(
                run,
                "tool.retryable_same_idempotency_key",
                {"tool_call_id": call.tool_call_id},
                commit=False,
            )
            return
        if state == "transport_sent_observed" and capability in {"receipt_first", "idempotency_index_only"}:
            call.status = "uncertain"
            call.recovery_decision = "reconcile_backoff"
            attempt.next_retry_at = _utcnow() + timedelta(seconds=self.backoff_seconds)
            runtime.append_event(run, "tool.uncertain", {"tool_call_id": call.tool_call_id, "status": "not_found"}, commit=False)
            return
        if state in {"backend_accepted", "effect_committed"}:
            call.status = "manual_intervention"
            call.recovery_decision = f"{state}_not_found_incident"
            call.error_code = "reconcile_not_found_after_commit"
            runtime.append_event(run, "tool.failed", {"tool_call_id": call.tool_call_id, "error_code": call.error_code}, commit=False)
            return
        call.status = "manual_intervention"
        call.recovery_decision = "not_found_manual_review"
        call.error_code = "reconcile_not_found"
        runtime.append_event(run, "tool.failed", {"tool_call_id": call.tool_call_id, "error_code": call.error_code}, commit=False)

    def _mark_needs_migration(
        self,
        *,
        run: AgentRun,
        call: AgentToolCall,
        result: ReconcileResult,
        record_attempt: bool = True,
    ) -> AgentToolCall:
        runtime = AgentRuntimeService(self.db)
        call.status = "needs_migration"
        call.recovery_decision = "backend_contract_migration_required"
        call.error_code = result.error_code or "unsupported_schema_version"
        call.error_message = result.error_message
        if record_attempt:
            self._record_attempt(call=call, result=result)
        block = self.migration_coordinator.create_tool_call_block(
            run=run,
            call=call,
            reason="backend_contract_migration_required",
            details=result.model_dump(mode="json"),
        )
        runtime.append_event(
            run,
            "tool.needs_migration",
            {"tool_call_id": call.tool_call_id, "block_id": block.block_id},
            commit=False,
        )
        runtime.append_event(run, "run.migration_blocked", {"block_id": block.block_id}, commit=False)
        return call

    def _record_attempt(self, *, call: AgentToolCall, result: ReconcileResult) -> AgentReconcileAttempt:
        attempt_seq = (
            self.db.scalar(
                select(func.max(AgentReconcileAttempt.attempt_seq))
                .where(AgentReconcileAttempt.tool_call_id == call.tool_call_id)
            )
            or 0
        ) + 1
        attempt = AgentReconcileAttempt(
            tool_call_id=call.tool_call_id,
            attempt_seq=attempt_seq,
            backend_name=call.backend_name or "",
            backend_operation=call.backend_operation or "",
            backend_contract_version=call.backend_contract_version or result.backend_contract_version,
            result_status=result.status,
            raw_result_object_key=result.raw_output_object_key,
            error_code=result.error_code,
            error_message=result.error_message,
        )
        self.db.add(attempt)
        self.db.flush()
        return attempt

    @staticmethod
    def _summary(run_id: str, calls: list[AgentToolCall]) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "processed": len(calls),
            "reconciled": sum(1 for call in calls if call.status == "succeeded"),
            "still_uncertain": sum(1 for call in calls if call.status in {"uncertain", "reconciling"}),
            "needs_migration": sum(1 for call in calls if call.status == "needs_migration"),
            "manual_intervention": sum(1 for call in calls if call.status == "manual_intervention"),
            "tool_call_ids": [call.tool_call_id for call in calls],
        }


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
