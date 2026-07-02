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
    AgentContextBuild,
    AgentEvidenceWatch,
    AgentEvent,
    AgentMigrationBlock,
    AgentApproval,
    AgentReconcileAttempt,
    AgentRun,
    AgentRuntimeSnapshot,
    AgentToolCall,
    ProjectMemory,
)
from app.models.user import User
from app.schemas.agent import ReconcileResult
from app.services.agent_runtime_service import (
    AGENT_CONTEXT_COMPACTION_OBJECT_KEY_PREFIX,
    AGENT_HISTORY_CONTEXT_COMPACTION_EVENT,
    AgentRuntimeService,
    RUN_TERMINAL_STATUSES,
)
from app.services.agent_tool_service import SAFE_SIDE_EFFECT_CLASSES
from app.services.permission_service import PermissionService


RECONCILE_ELIGIBLE_STATUSES = {"uncertain", "reconciling"}
RECONCILE_RESULT_STATUSES = {
    "succeeded",
    "running",
    "failed",
    "not_found",
    "conflict",
    "unsupported_schema_version",
}
RECONCILE_SCHEMA_SUPPORT_VALUES = {"supported", "unsupported", "adapter_required"}
RECONCILE_SUCCESS_RESULT_STATUSES = {"succeeded"}
RECONCILE_BACKOFF_RESULT_STATUSES = {"running", "not_found"}
RECONCILE_TERMINAL_FAILURE_RESULT_STATUSES = {"failed"}
RECONCILE_DIRECT_MANUAL_RESULT_STATUSES = {"conflict"}
RECONCILE_STATE_DEPENDENT_RESULT_STATUSES = {"not_found"}
RECONCILE_MIGRATION_RESULT_STATUSES = {"unsupported_schema_version"}
RECONCILE_BACKOFF_EFFECT_STATES = {"transport_sent_observed"}
RECONCILE_BACKOFF_CAPABILITIES = {"receipt_first", "idempotency_index_only"}
RECONCILE_RESULT_ENVELOPE_FIELDS = set(ReconcileResult.model_fields)
RECONCILE_SUMMARY_FIELDS = {
    "run_id",
    "processed",
    "skipped_backoff",
    "reconciled",
    "still_uncertain",
    "needs_migration",
    "manual_intervention",
    "tool_call_ids",
    "skipped_backoff_tool_calls",
}
AGENT_RECONCILE_SKIPPED_BACKOFF_ITEM_ID_PREFIX = "agent-reconcile-skipped-backoff"
RECONCILE_SKIPPED_BACKOFF_FIELDS = {"item_id", "tool_call_id", "next_retry_at", "attempt_seq", "result_status"}
PERMISSION_FRESHNESS_TOOL_STATUSES = {
    "planned",
    "approved",
    "executable",
    "failed_retryable",
    "uncertain",
    "reconciling",
}
PERMISSION_FRESHNESS_FIELDS = (
    "revoked_required_permission_count",
    "revoked_required_permissions",
)
PERMISSION_FRESHNESS_DETAIL_FIELDS = (
    "tool_call_id",
    "tool_name",
    "permission",
    "status",
)
PERMISSION_FRESHNESS_RESULT = "permission_stale"
PERMISSION_FRESHNESS_ACTION = "refresh_permissions_or_manual_review"
PERMISSION_FRESHNESS_REASON = "required_permission_revoked"
PENDING_APPROVAL_FRESHNESS_FIELDS = (
    "pending_approval_count",
    "expired_pending_approval_count",
    "stale_pending_approval_count",
    "pending_approval_details",
)
PENDING_APPROVAL_DETAIL_FIELDS = (
    "approval_id",
    "tool_call_id",
    "approval_lineage_id",
    "approval_epoch",
    "expires_at",
    "stale_reasons",
)
PENDING_APPROVAL_FRESHNESS_REASONS = (
    "pending_approval_expired",
    "pending_approval_stale",
    "pending_approval_after_wait",
)
PENDING_APPROVAL_DETAIL_STALE_REASONS = (
    "expired",
    "tool_call_missing",
    "immutable_mismatch",
    "pending_after_wait",
)
PENDING_APPROVAL_FRESHNESS_RESULT = "approval_stale"
PENDING_APPROVAL_FRESHNESS_ACTION = "supersede_or_refresh_approval"
ENVIRONMENT_FRESHNESS_FIELDS = (
    "environment_changed_count",
    "stale_evidence_watch_details",
)
ENVIRONMENT_FRESHNESS_RESULT = "environment_changed"
ENVIRONMENT_FRESHNESS_ACTION = "revalidate_before_side_effect"
ENVIRONMENT_FRESHNESS_REASON = "environment_updated"
STALE_EVIDENCE_WATCH_DETAIL_FIELDS = (
    "evidence_ref_id",
    "ref_type",
    "ref_id",
    "stale_reason",
)
ACTIVE_EVIDENCE_REVALIDATION_FIELDS = (
    "active_evidence_revalidation_count",
    "active_evidence_revalidation_details",
)
ACTIVE_EVIDENCE_REVALIDATION_DETAIL_FIELDS = (
    "evidence_ref_id",
    "ref_type",
    "ref_id",
    "mutability_class",
    "freshness_policy",
)
ACTIVE_EVIDENCE_REVALIDATION_RESULT = "evidence_stale"
ACTIVE_EVIDENCE_REVALIDATION_ACTIONS = (
    "materialize_latest_evidence",
    "fetch_evidence_and_rebuild_context",
)
ACTIVE_EVIDENCE_REVALIDATION_REASONS = (
    "ephemeral_latest_requires_materialization",
    "active_evidence_requires_revalidation",
)
RUNTIME_SNAPSHOT_FRESHNESS_FIELDS = (
    "checkpoint_runtime_snapshot_id",
    "run_runtime_snapshot_id",
    "runtime_snapshot_compatible",
)
RUNTIME_SNAPSHOT_FRESHNESS_RESULT = "too_old"
RUNTIME_SNAPSHOT_FRESHNESS_ACTION = "replan_from_latest_safe_state"
RUNTIME_SNAPSHOT_FRESHNESS_REASONS = (
    "runtime_snapshot_missing",
    "runtime_snapshot_mismatch",
)
RUNTIME_SNAPSHOT_FRESHNESS_ERROR_CODE = "checkpoint_stale_replan_required"
CHECKPOINT_CONTEXT_COMPACTION_FIELDS = (
    "context_compaction_object_key",
    "context_compaction_event_seq",
    "context_compaction_event_type",
    "context_compaction_available",
)
CHECKPOINT_CONTEXT_COMPACTION_RESULT = "too_old"
CHECKPOINT_CONTEXT_COMPACTION_ACTION = "replan_from_latest_safe_state"
CHECKPOINT_CONTEXT_COMPACTION_REASONS = (
    "context_compaction_reference_malformed",
    "context_compaction_reference_missing",
)
ACTIVE_POLICY_REF_ROLES = {"decision_dependency", "validation_evidence", "policy_dependency"}


def _is_active_policy_ref(item: dict[str, Any]) -> bool:
    return (
        item.get("active_for_policy") is True
        and item.get("dependency_role") in ACTIVE_POLICY_REF_ROLES
        and item.get("superseded_by_ref") is None
    )


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
        terminal_status = run.status if run.status in RUN_TERMINAL_STATUSES else None
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
        if open_blocks and terminal_status is None:
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
        terminal_status = run.status if run.status in RUN_TERMINAL_STATUSES else None
        block = self.db.scalar(
            select(AgentMigrationBlock)
            .where(AgentMigrationBlock.run_id == run_id, AgentMigrationBlock.block_id == block_id)
            .with_for_update()
        )
        if block is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent migration block not found")
        if block.status == "resolved":
            freshness = CheckpointFreshnessGate(self.db).evaluate(run=run, current_user=current_user)
            return block, self._terminal_resolve_freshness(
                freshness,
                terminal_status=terminal_status,
                block=block,
            )

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
        freshness = CheckpointFreshnessGate(self.db).evaluate(run=run, current_user=current_user)
        freshness = self._terminal_resolve_freshness(
            freshness,
            terminal_status=terminal_status,
            block=block,
        )
        checkpoint = self.db.get(AgentCheckpoint, run.last_checkpoint_id) if run.last_checkpoint_id else None
        if checkpoint is not None:
            checkpoint.freshness_metadata_json = freshness
        if run.migration_block_count == 0:
            if terminal_status is not None:
                run.status = terminal_status
            elif freshness["action"] == "continue_from_checkpoint":
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

    def _terminal_resolve_freshness(
        self,
        freshness: dict[str, Any],
        *,
        terminal_status: str | None,
        block: AgentMigrationBlock,
    ) -> dict[str, Any]:
        if terminal_status is None:
            return freshness
        tool_call_status = None
        if block.tool_call_id:
            call = self.db.scalar(select(AgentToolCall).where(AgentToolCall.tool_call_id == block.tool_call_id))
            if call is not None:
                tool_call_status = call.status
        post_resolve_next_action = (
            "reconcile_run"
            if tool_call_status in {"needs_migration", "uncertain", "reconciling"}
            else "none"
        )
        decorated = dict(freshness)
        decorated.update({
            "terminal_run_preserved": True,
            "terminal_run_status": terminal_status,
            "resolve_preserves_terminal_run": True,
            "post_resolve_next_action": post_resolve_next_action,
        })
        if tool_call_status is not None:
            decorated["tool_call_status_after_resolve"] = tool_call_status
        return decorated

    def _refresh_run_block_state_after_resolution(self, run: AgentRun) -> None:
        terminal_status = run.status if run.status in RUN_TERMINAL_STATUSES else None
        open_blocks = list(self.db.scalars(
            select(AgentMigrationBlock).where(
                AgentMigrationBlock.run_id == run.run_id,
                AgentMigrationBlock.status == "open",
            )
        ).all())
        run.migration_block_count = len(open_blocks)
        run.blocking_tool_call_ids_json = [item.tool_call_id for item in open_blocks if item.tool_call_id]
        if open_blocks and terminal_status is None:
            run.status = "migration_blocked"


class CheckpointFreshnessGate:
    def __init__(self, db: Session, *, max_checkpoint_age_seconds: int = 4 * 60 * 60):
        self.db = db
        self.max_checkpoint_age_seconds = max_checkpoint_age_seconds
        self.permission_service = PermissionService(db)

    def evaluate(self, *, run: AgentRun, current_user: User | None = None) -> dict[str, Any]:
        now = _utcnow()
        checks: dict[str, Any] = {
            "checked_at": now.isoformat(),
            "run_id": run.run_id,
            "checkpoint_id": run.last_checkpoint_id,
            "checkpoint_age_seconds": None,
            "checkpoint_runtime_snapshot_id": None,
            "run_runtime_snapshot_id": run.runtime_snapshot_id,
            "runtime_snapshot_compatible": False,
            "open_migration_block_count": 0,
            "stale_evidence_watch_count": 0,
            "environment_changed_count": 0,
            "stale_evidence_watch_details": [],
            "active_evidence_revalidation_count": 0,
            "active_evidence_revalidation_details": [],
            "active_memory_needs_revalidation_count": 0,
            "active_memory_needs_revalidation_ids": [],
            "pending_approval_count": 0,
            "expired_pending_approval_count": 0,
            "stale_pending_approval_count": 0,
            "pending_approval_details": [],
            "revoked_required_permission_count": 0,
            "revoked_required_permissions": [],
            "backend_contract_missing_count": 0,
            "context_compaction_object_key": None,
            "context_compaction_event_seq": None,
            "context_compaction_event_type": None,
            "context_compaction_available": False,
            "result": "fresh",
            "action": "continue_from_checkpoint",
            "reason": "fresh",
        }
        checkpoint = self.db.get(AgentCheckpoint, run.last_checkpoint_id) if run.last_checkpoint_id else None
        if checkpoint is None:
            checks.update(result="too_old", action="replan_from_latest_safe_state", reason="checkpoint_missing")
            return checks
        compaction_metadata = self._checkpoint_context_compaction_metadata(run=run, checkpoint=checkpoint)
        compaction_invalid_reason = compaction_metadata.pop("_invalid_reason")
        checks.update(compaction_metadata)
        if compaction_invalid_reason is not None:
            checks.update(
                result=CHECKPOINT_CONTEXT_COMPACTION_RESULT,
                action=CHECKPOINT_CONTEXT_COMPACTION_ACTION,
                reason=compaction_invalid_reason,
            )
            return checks
        checks["checkpoint_runtime_snapshot_id"] = checkpoint.runtime_snapshot_id
        checks["checkpoint_age_seconds"] = int((now - checkpoint.created_at).total_seconds())
        if checks["checkpoint_age_seconds"] > self.max_checkpoint_age_seconds:
            checks.update(result="too_old", action="replan_from_latest_safe_state", reason="checkpoint_too_old")
            return checks

        snapshot_exists = self.db.scalar(
            select(AgentRuntimeSnapshot.id).where(
                AgentRuntimeSnapshot.project_id == run.project_id,
                AgentRuntimeSnapshot.snapshot_id == checkpoint.runtime_snapshot_id,
            )
        )
        if snapshot_exists is None:
            checks.update(
                result=RUNTIME_SNAPSHOT_FRESHNESS_RESULT,
                action=RUNTIME_SNAPSHOT_FRESHNESS_ACTION,
                reason=RUNTIME_SNAPSHOT_FRESHNESS_REASONS[0],
            )
            return checks
        if checkpoint.runtime_snapshot_id != run.runtime_snapshot_id:
            checks.update(
                result=RUNTIME_SNAPSHOT_FRESHNESS_RESULT,
                action=RUNTIME_SNAPSHOT_FRESHNESS_ACTION,
                reason=RUNTIME_SNAPSHOT_FRESHNESS_REASONS[1],
            )
            return checks
        checks["runtime_snapshot_compatible"] = True

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

        stale_evidence = self._stale_evidence_freshness(run=run)
        checks["stale_evidence_watch_count"] = stale_evidence["count"]
        checks["environment_changed_count"] = stale_evidence["environment_changed_count"]
        checks["stale_evidence_watch_details"] = stale_evidence["details"]
        if stale_evidence["environment_changed_count"]:
            checks.update(
                result=ENVIRONMENT_FRESHNESS_RESULT,
                action=ENVIRONMENT_FRESHNESS_ACTION,
                reason=ENVIRONMENT_FRESHNESS_REASON,
            )
            return checks
        if stale_evidence["count"]:
            checks.update(result="evidence_stale", action="fetch_evidence_and_rebuild_context", reason="stale_evidence_watch")
            return checks

        active_revalidation = self._active_evidence_revalidation(run=run)
        checks["active_evidence_revalidation_count"] = active_revalidation["count"]
        checks["active_evidence_revalidation_details"] = active_revalidation["details"]
        if active_revalidation["count"]:
            checks.update(
                result=ACTIVE_EVIDENCE_REVALIDATION_RESULT,
                action=active_revalidation["action"],
                reason=active_revalidation["reason"],
            )
            return checks

        memory_freshness = self._active_memory_freshness(run=run)
        checks["active_memory_needs_revalidation_count"] = memory_freshness["count"]
        checks["active_memory_needs_revalidation_ids"] = memory_freshness["memory_ids"]
        if memory_freshness["count"]:
            checks.update(
                result="evidence_stale",
                action="fetch_evidence_and_rebuild_context",
                reason="active_memory_needs_revalidation",
            )
            return checks

        approval_freshness = self._pending_approval_freshness(run=run, now=now)
        checks["pending_approval_count"] = approval_freshness["pending_count"]
        checks["expired_pending_approval_count"] = approval_freshness["expired_count"]
        checks["stale_pending_approval_count"] = approval_freshness["stale_count"]
        checks["pending_approval_details"] = approval_freshness["details"]
        if approval_freshness["pending_count"]:
            if approval_freshness["expired_count"]:
                reason = PENDING_APPROVAL_FRESHNESS_REASONS[0]
            elif approval_freshness["stale_count"]:
                reason = PENDING_APPROVAL_FRESHNESS_REASONS[1]
            else:
                reason = PENDING_APPROVAL_FRESHNESS_REASONS[2]
            checks.update(
                result=PENDING_APPROVAL_FRESHNESS_RESULT,
                action=PENDING_APPROVAL_FRESHNESS_ACTION,
                reason=reason,
            )
            return checks

        permission_freshness = self._permission_freshness(run=run, current_user=current_user)
        checks["revoked_required_permission_count"] = permission_freshness["count"]
        checks["revoked_required_permissions"] = permission_freshness["revoked_required_permissions"]
        if permission_freshness["count"]:
            checks.update(
                result=PERMISSION_FRESHNESS_RESULT,
                action=PERMISSION_FRESHNESS_ACTION,
                reason=PERMISSION_FRESHNESS_REASON,
            )
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

    def _checkpoint_context_compaction_metadata(
        self,
        *,
        run: AgentRun,
        checkpoint: AgentCheckpoint,
    ) -> dict[str, Any]:
        object_key = checkpoint.context_compaction_object_key
        metadata: dict[str, Any] = {
            "context_compaction_object_key": object_key,
            "context_compaction_event_seq": None,
            "context_compaction_event_type": None,
            "context_compaction_available": False,
            "_invalid_reason": None,
        }
        if not object_key:
            return metadata
        prefix = f"{AGENT_CONTEXT_COMPACTION_OBJECT_KEY_PREFIX}://{run.run_id}/"
        if not object_key.startswith(prefix):
            metadata["_invalid_reason"] = CHECKPOINT_CONTEXT_COMPACTION_REASONS[0]
            return metadata
        try:
            event_seq = int(object_key.removeprefix(prefix))
        except ValueError:
            metadata["_invalid_reason"] = CHECKPOINT_CONTEXT_COMPACTION_REASONS[0]
            return metadata
        event = self.db.scalar(
            select(AgentEvent).where(
                AgentEvent.run_id == run.run_id,
                AgentEvent.event_seq == event_seq,
                AgentEvent.event_type == AGENT_HISTORY_CONTEXT_COMPACTION_EVENT,
            )
        )
        if event is None:
            metadata["context_compaction_event_seq"] = event_seq
            metadata["context_compaction_event_type"] = AGENT_HISTORY_CONTEXT_COMPACTION_EVENT
            metadata["_invalid_reason"] = CHECKPOINT_CONTEXT_COMPACTION_REASONS[1]
            return metadata
        metadata["context_compaction_event_seq"] = event.event_seq
        metadata["context_compaction_event_type"] = event.event_type
        metadata["context_compaction_available"] = True
        return metadata

    def _stale_evidence_freshness(self, *, run: AgentRun) -> dict[str, Any]:
        watches = list(
            self.db.scalars(
                select(AgentEvidenceWatch).where(
                    AgentEvidenceWatch.run_id == run.run_id,
                    AgentEvidenceWatch.watch_status == "stale",
                )
            ).all()
        )
        details = [
            {
                "evidence_watch_id": watch.evidence_watch_id,
                "evidence_ref_id": watch.evidence_ref_id,
                "ref_type": watch.ref_type,
                "ref_id": watch.ref_id,
                "stale_reason": watch.stale_reason,
            }
            for watch in watches
        ]
        environment_changed_count = sum(
            1
            for watch in watches
            if watch.ref_type == "environment" or watch.stale_reason == "environment.updated"
        )
        return {
            "count": len(watches),
            "environment_changed_count": environment_changed_count,
            "details": details,
        }

    def _active_evidence_revalidation(self, *, run: AgentRun) -> dict[str, Any]:
        policy_refs = self._latest_context_policy_refs(run=run)
        latest_details: list[dict[str, Any]] = []
        revalidation_details: list[dict[str, Any]] = []
        for item in policy_refs:
            if not _is_active_policy_ref(item):
                continue
            detail = {
                "evidence_ref_id": item.get("evidence_ref_id"),
                "ref_type": item.get("ref_type"),
                "ref_id": item.get("ref_id"),
                "mutability_class": item.get("mutability_class"),
                "freshness_policy": item.get("freshness_policy"),
                "dependency_role": item.get("dependency_role"),
            }
            if item.get("ref_type") == "latest_execution_sample" or item.get("mutability_class") == "ephemeral_latest":
                latest_details.append(detail)
                continue
            if (
                item.get("freshness_policy") == "revalidate_on_resume"
                or item.get("mutability_class") == "external_uncontrolled"
                or item.get("ref_type") == "external_doc"
            ):
                revalidation_details.append(detail)

        details = latest_details + revalidation_details
        if latest_details:
            return {
                "count": len(details),
                "details": details,
                "action": ACTIVE_EVIDENCE_REVALIDATION_ACTIONS[0],
                "reason": ACTIVE_EVIDENCE_REVALIDATION_REASONS[0],
            }
        if revalidation_details:
            return {
                "count": len(details),
                "details": details,
                "action": ACTIVE_EVIDENCE_REVALIDATION_ACTIONS[1],
                "reason": ACTIVE_EVIDENCE_REVALIDATION_REASONS[1],
            }
        return {
            "count": 0,
            "details": [],
            "action": "continue_from_checkpoint",
            "reason": "fresh",
        }

    def _active_memory_freshness(self, *, run: AgentRun) -> dict[str, Any]:
        policy_refs = self._latest_context_policy_refs(run=run)
        memory_ids = sorted(
            {
                int(item["ref_id"])
                for item in policy_refs
                if item.get("ref_type") == "memory"
                and _is_active_policy_ref(item)
                and str(item.get("ref_id") or "").isdigit()
            }
        )
        if not memory_ids:
            return {"count": 0, "memory_ids": []}
        memories = list(
            self.db.scalars(
                select(ProjectMemory).where(
                    ProjectMemory.project_id == run.project_id,
                    ProjectMemory.id.in_(memory_ids),
                )
            ).all()
        )
        stale_memory_ids = sorted(
            memory.id
            for memory in memories
            if memory.status == "needs_revalidation" or memory.stale_score >= 0.8
        )
        return {"count": len(stale_memory_ids), "memory_ids": stale_memory_ids}

    def _latest_context_policy_refs(self, *, run: AgentRun) -> list[dict[str, Any]]:
        latest_context = self.db.scalar(
            select(AgentContextBuild)
            .where(AgentContextBuild.run_id == run.run_id)
            .order_by(
                AgentContextBuild.iteration.desc(),
                AgentContextBuild.step_index.desc(),
                AgentContextBuild.build_seq.desc(),
            )
        )
        if latest_context is None:
            return []
        return list((latest_context.build_metadata_json or {}).get("policy_refs") or [])

    def _pending_approval_freshness(self, *, run: AgentRun, now: datetime) -> dict[str, Any]:
        approvals = list(
            self.db.scalars(
                select(AgentApproval).where(
                    AgentApproval.run_id == run.run_id,
                    AgentApproval.approval_status == "pending",
                )
            ).all()
        )
        details: list[dict[str, Any]] = []
        expired_count = 0
        stale_count = 0
        for approval in approvals:
            reasons: list[str] = []
            call = self.db.scalar(select(AgentToolCall).where(AgentToolCall.tool_call_id == approval.tool_call_id))
            if approval.expires_at is not None and approval.expires_at <= now:
                expired_count += 1
                reasons.append(PENDING_APPROVAL_DETAIL_STALE_REASONS[0])
            if call is None:
                stale_count += 1
                reasons.append(PENDING_APPROVAL_DETAIL_STALE_REASONS[1])
            elif (
                approval.input_hash != call.input_hash
                or approval.runtime_snapshot_id != call.runtime_snapshot_id
                or approval.resource_scope_hash != (call.approval_scope_hash or call.input_hash)
                or approval.approval_lineage_id != call.approval_lineage_id
                or approval.approval_epoch != call.approval_epoch
            ):
                stale_count += 1
                reasons.append(PENDING_APPROVAL_DETAIL_STALE_REASONS[2])
            details.append({
                "approval_id": approval.approval_id,
                "tool_call_id": approval.tool_call_id,
                "approval_lineage_id": approval.approval_lineage_id,
                "approval_epoch": approval.approval_epoch,
                "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
                "stale_reasons": reasons or [PENDING_APPROVAL_DETAIL_STALE_REASONS[3]],
            })
        return {
            "pending_count": len(approvals),
            "expired_count": expired_count,
            "stale_count": stale_count,
            "details": details,
        }

    def _permission_freshness(self, *, run: AgentRun, current_user: User | None) -> dict[str, Any]:
        if current_user is None:
            return {"count": 0, "revoked_required_permissions": []}
        calls = list(
            self.db.scalars(
                select(AgentToolCall).where(
                    AgentToolCall.run_id == run.run_id,
                    AgentToolCall.status.in_(PERMISSION_FRESHNESS_TOOL_STATUSES),
                )
            ).all()
        )
        revoked: list[dict[str, Any]] = []
        for call in calls:
            for permission in call.required_permissions_json or []:
                if self.permission_service.has_project_permission(current_user, run.project_id, permission):
                    continue
                revoked.append({
                    "tool_call_id": call.tool_call_id,
                    "tool_name": call.tool_name,
                    "permission": permission,
                    "status": call.status,
                })
        return {"count": len(revoked), "revoked_required_permissions": revoked}


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
        calls = list(self.db.scalars(
            select(AgentToolCall)
            .where(
                AgentToolCall.run_id == run_id,
                AgentToolCall.status.in_(RECONCILE_ELIGIBLE_STATUSES),
            )
            .order_by(AgentToolCall.step_index.asc(), AgentToolCall.attempt_index.asc())
        ).all())
        now = _utcnow()
        due_calls: list[AgentToolCall] = []
        skipped_backoff: list[dict[str, Any]] = []
        for call in calls:
            latest_attempt = self._latest_attempt(call.tool_call_id)
            if latest_attempt is not None and latest_attempt.next_retry_at is not None and latest_attempt.next_retry_at > now:
                skipped_backoff.append({
                    "item_id": _reconcile_skipped_backoff_item_id(call.tool_call_id, latest_attempt.attempt_seq),
                    "tool_call_id": call.tool_call_id,
                    "next_retry_at": latest_attempt.next_retry_at.isoformat(),
                    "attempt_seq": latest_attempt.attempt_seq,
                    "result_status": latest_attempt.result_status,
                })
                continue
            due_calls.append(call)

        processed = [self.reconcile_tool_call(call=call, run=run) for call in due_calls]
        self.db.commit()
        return self._summary(run_id, processed, skipped_backoff=skipped_backoff)

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
            call.error_code = "backend_reconcile_not_supported"
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

        if result.status in RECONCILE_SUCCESS_RESULT_STATUSES:
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
        if result.status in RECONCILE_STATE_DEPENDENT_RESULT_STATUSES:
            self._handle_not_found(run=run, call=call, attempt=attempt)
            return call
        if result.status in RECONCILE_DIRECT_MANUAL_RESULT_STATUSES:
            call.status = "manual_intervention"
            call.recovery_decision = "idempotency_conflict"
            call.error_code = result.error_code or "idempotency_conflict"
            call.error_message = result.error_message
            runtime.append_event(run, "tool.failed", {"tool_call_id": call.tool_call_id, "error_code": call.error_code}, commit=False)
            return call
        if result.status in RECONCILE_TERMINAL_FAILURE_RESULT_STATUSES:
            call.status = "failed"
            call.recovery_decision = "mark_failed_from_reconcile"
            call.error_code = result.error_code or "backend_reconcile_failed"
            call.error_message = result.error_message
            runtime.append_event(run, "tool.failed", {"tool_call_id": call.tool_call_id, "error_code": call.error_code}, commit=False)
            return call
        if result.status in RECONCILE_MIGRATION_RESULT_STATUSES:
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
        if state in RECONCILE_BACKOFF_EFFECT_STATES and capability in RECONCILE_BACKOFF_CAPABILITIES:
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

    def _latest_attempt(self, tool_call_id: str) -> AgentReconcileAttempt | None:
        return self.db.scalar(
            select(AgentReconcileAttempt)
            .where(AgentReconcileAttempt.tool_call_id == tool_call_id)
            .order_by(AgentReconcileAttempt.attempt_seq.desc())
            .limit(1)
        )

    @staticmethod
    def _summary(
        run_id: str,
        calls: list[AgentToolCall],
        *,
        skipped_backoff: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        skipped = skipped_backoff or []
        return {
            "run_id": run_id,
            "processed": len(calls),
            "skipped_backoff": len(skipped),
            "reconciled": sum(1 for call in calls if call.status == "succeeded"),
            "still_uncertain": sum(1 for call in calls if call.status in {"uncertain", "reconciling"}),
            "needs_migration": sum(1 for call in calls if call.status == "needs_migration"),
            "manual_intervention": sum(1 for call in calls if call.status == "manual_intervention"),
            "tool_call_ids": [call.tool_call_id for call in calls],
            "skipped_backoff_tool_calls": skipped,
        }


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _reconcile_skipped_backoff_item_id(tool_call_id: str, attempt_seq: int) -> str:
    return f"{AGENT_RECONCILE_SKIPPED_BACKOFF_ITEM_ID_PREFIX}://{tool_call_id}/{attempt_seq}"
