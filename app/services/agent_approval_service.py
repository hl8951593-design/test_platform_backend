from __future__ import annotations

import uuid
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.sensitive_data import mask_sensitive, request_fingerprint
from app.models.agent import (
    AgentApproval,
    AgentApprovalLineage,
    AgentApprovalMutationLog,
    AgentContextBuild,
    AgentRun,
    AgentToolCall,
    AgentWorkerQueue,
)
from app.models.user import User
from app.schemas.agent import AgentApprovalDecisionRequest, AgentToolCallCreateRequest
from app.services.agent_loop_service import EvidenceRefResolver, EvidenceWatchService
from app.services.agent_tool_service import ToolPolicyResolver, ToolRegistry
from app.services.permission_service import PermissionService


APPROVAL_FINAL_STATUSES = {"approved", "rejected", "expired", "superseded"}
APPROVAL_IMMUTABLE_FIELDS = (
    "input_hash",
    "runtime_snapshot_id",
    "resource_scope_hash",
    "approval_lineage_id",
    "approval_epoch",
)
APPROVAL_MUTATION_TYPES = {"create", "approve", "reject", "supersede", "create_replacement", "expire"}
APPROVAL_EVENT_TYPES = {
    "approval.created",
    "approval.approved",
    "approval.rejected",
    "approval.superseded",
    "approval.expired",
    "approval.approve_conflict",
    "approval.reject_conflict",
}
APPROVAL_CONFLICT_ERROR_CODES = {
    "approval_stale_or_superseded",
    "approval_epoch_conflict",
    "approval_input_changed",
    "tool_call_not_approvable",
    "cannot_supersede_executing_call",
}
APPROVAL_EXPIRE_AUDIT_FIELDS = (
    "project_id",
    "generated_at",
    "due_count",
    "candidate_lineage_count",
    "oldest_due_lag_ms",
    "lineage_hotspot_count",
    "hotspot_lineage_ids",
    "batch_safe",
    "derived_from",
)
APPROVAL_EXPIRE_PROCESS_FIELDS = (
    "project_id",
    "generated_at",
    "limit",
    "attempted",
    "expired",
    "skipped",
    "skipped_duplicate_lineage_count",
    "processed_lineage_ids",
    "lineage_lock_wait_ms",
    "lineage_lock_skip_total",
    "due_before",
    "due_after",
    "oldest_due_lag_ms_before",
    "oldest_due_lag_ms_after",
    "lineage_hotspot_count_before",
    "lineage_hotspot_count_after",
    "batch_safe",
    "derived_from",
)
APPROVAL_EXPIRE_DERIVED_FROM_FIELDS = (
    "approval_table",
    "mutation_log_table",
    "candidate_order",
    "processing_model",
    "scope",
)
HIGH_RISK_SIDE_EFFECT_CLASSES = {"business_create", "business_update", "destructive", "external_effect"}
TRUSTED_HIGH_RISK_EVIDENCE_REF_TYPES = {"system_record", "project_config", "execution_record", "document_imported"}
TRUSTED_HIGH_RISK_EVIDENCE_AUTHORITIES = {"system_record", "project_config", "execution_record", "document_imported"}
APPROVABLE_TOOL_CALL_STATUSES = {"planned", "pending_approval"}
SUPERSEDE_BLOCKED_TOOL_CALL_STATUSES = {"leased", "running_pre_effect", "effect_sent", "uncertain", "reconciling", "succeeded"}


class PolicyManager:
    def __init__(self, db: Session):
        self.db = db
        self.permission_service = PermissionService(db)

    def require_run_access(self, *, run: AgentRun, current_user: User) -> None:
        self.permission_service.require_project_access(current_user, run.project_id)

    def require_tool_execution_permissions(self, *, call: AgentToolCall, run: AgentRun, current_user: User) -> None:
        for permission in call.required_permissions_json:
            self.permission_service.require_project_permission(current_user, run.project_id, permission)

    def require_approval_permissions(self, *, approval: AgentApproval, current_user: User) -> None:
        for permission in approval.required_permissions_json:
            self.permission_service.require_project_permission(current_user, approval.project_id, permission)

    def ensure_approval_allows_execution(self, *, call: AgentToolCall) -> None:
        if not call.approval_required:
            return
        if not call.approved_approval_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "approval_required_before_execution"})
        approval = self.db.scalar(
            select(AgentApproval).where(AgentApproval.approval_id == call.approved_approval_id)
        )
        if approval is None or approval.approval_status != "approved":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "approval_required_before_execution"})
        if (
            approval.input_hash != call.input_hash
            or approval.runtime_snapshot_id != call.runtime_snapshot_id
            or approval.resource_scope_hash != call.approval_scope_hash
            or approval.approval_lineage_id != call.approval_lineage_id
            or approval.approval_epoch != call.approval_epoch
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "approval_stale_or_superseded"})

    def ensure_context_allows_execution(self, *, call: AgentToolCall) -> None:
        if call.resolved_side_effect_class not in HIGH_RISK_SIDE_EFFECT_CLASSES:
            return
        if not call.decision_context_build_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "context_decision_build_required"})
        build = self.db.scalar(
            select(AgentContextBuild).where(AgentContextBuild.context_build_id == call.decision_context_build_id)
        )
        if build is None or build.run_id != call.run_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "context_decision_build_required"})
        if not build.required_evidence_complete:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "required_evidence_incomplete_for_high_risk"},
            )
        policy_refs = call.policy_evidence_refs_json or []
        if not any(_is_trusted_high_risk_evidence(ref) for ref in policy_refs):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "high_risk_action_cannot_depend_only_on_memory"},
            )
        if any(
            ref.get("ref_type") == "memory" and str(ref.get("authority") or "").startswith("memory:agent")
            for ref in policy_refs
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "agent_memory_used_for_high_risk"},
            )


def _is_trusted_high_risk_evidence(ref: dict[str, Any]) -> bool:
    ref_type = str(ref.get("ref_type") or "")
    authority = str(ref.get("authority") or "")
    trusted_source = ref_type in TRUSTED_HIGH_RISK_EVIDENCE_REF_TYPES or authority in TRUSTED_HIGH_RISK_EVIDENCE_AUTHORITIES
    if not trusted_source:
        return False
    mutability_class = str(ref.get("mutability_class") or "")
    if mutability_class in {"immutable", "versioned"} and (
        ref.get("content_hash") or ref.get("version_id") or ref.get("snapshot_id")
    ):
        return True
    return str(ref.get("freshness_policy") or "") == "revalidate_before_side_effect"


class ApprovalService:
    def __init__(self, db: Session):
        self.db = db
        self.policy_manager = PolicyManager(db)

    def create_pending_approval(
        self,
        *,
        call: AgentToolCall,
        run: AgentRun,
        current_user: User,
        expires_at: datetime | None = None,
        reason: str | None = None,
        commit: bool = True,
    ) -> AgentApproval:
        existing = self.get_current_approval(tool_call_id=call.tool_call_id)
        if existing is not None and existing.approval_status == "pending":
            return existing

        now = _utcnow()
        lineage_id = call.approval_lineage_id or f"agent-appr-lineage-{uuid.uuid4().hex}"
        lineage = AgentApprovalLineage(
            approval_lineage_id=lineage_id,
            run_id=run.run_id,
            tool_call_id=call.tool_call_id,
            project_id=run.project_id,
            current_epoch=1,
            status="pending",
            immutable_input_hash=call.input_hash,
            runtime_snapshot_id=call.runtime_snapshot_id,
            resource_scope_hash=call.approval_scope_hash or call.input_hash,
            created_by=current_user.id,
            created_at=now,
            updated_at=now,
        )
        approval = AgentApproval(
            approval_id=f"agent-appr-{uuid.uuid4().hex}",
            approval_lineage_id=lineage_id,
            approval_epoch=1,
            run_id=run.run_id,
            tool_call_id=call.tool_call_id,
            project_id=run.project_id,
            approval_status="pending",
            requested_by=current_user.id,
            input_hash=call.input_hash,
            runtime_snapshot_id=call.runtime_snapshot_id,
            resource_scope_hash=call.approval_scope_hash or call.input_hash,
            approval_reason=reason or "tool_call_requires_approval",
            required_permissions_json=list(call.required_permissions_json),
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )
        call.approval_required = True
        call.approval_lineage_id = lineage_id
        call.approval_epoch = 1
        self.db.add(lineage)
        self.db.add(approval)
        mutation = self._add_mutation(
            approval=approval,
            lineage=lineage,
            mutation_type="create",
            from_status=None,
            to_status="pending",
            actor_user_id=current_user.id,
            reason=reason,
        )
        from app.services.agent_runtime_service import AgentRuntimeService

        AgentRuntimeService(self.db).append_event(
            run,
            "approval.created",
            {
                "tool_call_id": call.tool_call_id,
                "approval_id": approval.approval_id,
                "approval_lineage_id": lineage_id,
                "approval_epoch": approval.approval_epoch,
            },
            commit=False,
        )
        if commit:
            self.db.commit()
            self.db.refresh(approval)
        else:
            self.db.flush()
        _ = mutation
        return approval

    def approve(
        self,
        *,
        tool_call_id: str,
        payload: AgentApprovalDecisionRequest,
        current_user: User,
    ) -> tuple[AgentApproval, AgentApprovalLineage, AgentToolCall, AgentApprovalMutationLog]:
        return ApprovalMutationGuard(self.db).approve(
            tool_call_id=tool_call_id,
            payload=payload,
            current_user=current_user,
        )

    def reject(
        self,
        *,
        tool_call_id: str,
        payload: AgentApprovalDecisionRequest,
        current_user: User,
    ) -> tuple[AgentApproval, AgentApprovalLineage, AgentToolCall, AgentApprovalMutationLog]:
        return ApprovalMutationGuard(self.db).reject(
            tool_call_id=tool_call_id,
            payload=payload,
            current_user=current_user,
        )

    def supersede_with_replacement(
        self,
        *,
        tool_call_id: str,
        replacement_payload: AgentToolCallCreateRequest,
        current_user: User,
        reason: str | None = None,
    ) -> tuple[AgentApproval, AgentApprovalLineage, AgentToolCall, AgentApproval, AgentApprovalMutationLog, AgentApprovalMutationLog]:
        return ApprovalMutationGuard(self.db).supersede_with_replacement(
            tool_call_id=tool_call_id,
            replacement_payload=replacement_payload,
            current_user=current_user,
            reason=reason,
        )

    def get_current_approval(self, *, tool_call_id: str) -> AgentApproval | None:
        return self.db.scalar(
            select(AgentApproval)
            .where(AgentApproval.tool_call_id == tool_call_id)
            .order_by(AgentApproval.approval_epoch.desc(), AgentApproval.created_at.desc())
            .limit(1)
        )

    def get_lineage(self, *, approval_lineage_id: str | None) -> AgentApprovalLineage | None:
        if approval_lineage_id is None:
            return None
        return self.db.scalar(
            select(AgentApprovalLineage).where(AgentApprovalLineage.approval_lineage_id == approval_lineage_id)
        )

    def list_run_approvals(self, *, run_id: str, current_user: User) -> list[AgentApproval]:
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == run_id))
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
        self.policy_manager.require_run_access(run=run, current_user=current_user)
        return list(
            self.db.scalars(
                select(AgentApproval)
                .where(AgentApproval.run_id == run_id)
                .order_by(AgentApproval.created_at.desc(), AgentApproval.approval_epoch.desc())
            ).all()
        )

    def _add_mutation(
        self,
        *,
        approval: AgentApproval,
        lineage: AgentApprovalLineage,
        mutation_type: str,
        from_status: str | None,
        to_status: str,
        actor_user_id: int | None,
        reason: str | None,
        details_json: dict[str, Any] | None = None,
    ) -> AgentApprovalMutationLog:
        mutation = AgentApprovalMutationLog(
            approval_lineage_id=lineage.approval_lineage_id,
            approval_id=approval.approval_id,
            tool_call_id=approval.tool_call_id,
            run_id=approval.run_id,
            mutation_type=mutation_type,
            from_status=from_status,
            to_status=to_status,
            actor_user_id=actor_user_id,
            reason=reason,
            details_json=details_json,
        )
        self.db.add(mutation)
        return mutation


class ApprovalMutationGuard:
    def __init__(self, db: Session):
        self.db = db
        self.policy_manager = PolicyManager(db)
        self.tool_registry = ToolRegistry()
        self.tool_policy_resolver = ToolPolicyResolver()

    def approve(
        self,
        *,
        tool_call_id: str,
        payload: AgentApprovalDecisionRequest,
        current_user: User,
    ) -> tuple[AgentApproval, AgentApprovalLineage, AgentToolCall, AgentApprovalMutationLog]:
        lineage, call, approval, run, lineage_lock_wait_ms = self._lock_context(
            tool_call_id=tool_call_id,
            payload=payload,
            action="approve",
        )
        self.policy_manager.require_run_access(run=run, current_user=current_user)
        self.policy_manager.require_approval_permissions(approval=approval, current_user=current_user)
        if self._is_idempotent_approved_decision(approval=approval, call=call, payload=payload):
            mutation = self._latest_mutation(approval=approval, mutation_type="approve")
            if mutation is not None:
                return approval, lineage, call, mutation
        try:
            self._validate_pending_immutable(approval=approval, payload=payload)
            self._expire_if_needed(
                approval=approval,
                lineage=lineage,
                call=call,
                run=run,
                lineage_lock_wait_ms=lineage_lock_wait_ms,
            )
            self._validate_call_approvable(call)
        except HTTPException as exc:
            self._record_decision_conflict(
                action="approve",
                run=run,
                call=call,
                lineage=lineage,
                approval=approval,
                payload=payload,
                error_code=_error_code(exc),
            )
            raise

        now = _utcnow()
        from_status = approval.approval_status
        approval.approval_status = "approved"
        approval.decided_by = current_user.id
        approval.decided_at = now
        approval.decision_reason = payload.reason
        lineage.status = "approved"
        lineage.updated_at = now
        call.approved_approval_id = approval.approval_id
        call.approved_by = current_user.id
        call.approved_at = now
        call.approval_epoch = approval.approval_epoch
        call.error_code = None
        call.error_message = None

        mutation = self._add_mutation(
            approval=approval,
            lineage=lineage,
            mutation_type="approve",
            from_status=from_status,
            to_status="approved",
            actor_user_id=current_user.id,
            reason=payload.reason,
            details_json={"lineage_lock_wait_ms": lineage_lock_wait_ms},
        )
        from app.services.agent_runtime_service import AgentRuntimeService

        AgentRuntimeService(self.db).append_event(
            run,
            "approval.approved",
            {
                "tool_call_id": call.tool_call_id,
                "approval_id": approval.approval_id,
                "approval_lineage_id": lineage.approval_lineage_id,
                "approval_epoch": approval.approval_epoch,
            },
            commit=False,
        )
        self._release_or_enqueue(call)
        self.db.commit()
        self.db.refresh(approval)
        self.db.refresh(lineage)
        self.db.refresh(call)
        self.db.refresh(mutation)
        return approval, lineage, call, mutation

    def _is_idempotent_approved_decision(
        self,
        *,
        approval: AgentApproval,
        call: AgentToolCall,
        payload: AgentApprovalDecisionRequest,
    ) -> bool:
        return (
            approval.approval_status == "approved"
            and call.approved_approval_id == approval.approval_id
            and approval.input_hash == payload.input_hash
            and approval.runtime_snapshot_id == payload.runtime_snapshot_id
            and approval.resource_scope_hash == payload.resource_scope_hash
            and approval.approval_lineage_id == payload.approval_lineage_id
            and approval.approval_epoch == payload.approval_epoch
        )

    def _latest_mutation(
        self,
        *,
        approval: AgentApproval,
        mutation_type: str,
    ) -> AgentApprovalMutationLog | None:
        return self.db.scalar(
            select(AgentApprovalMutationLog)
            .where(
                AgentApprovalMutationLog.approval_id == approval.approval_id,
                AgentApprovalMutationLog.mutation_type == mutation_type,
            )
            .order_by(AgentApprovalMutationLog.created_at.desc(), AgentApprovalMutationLog.id.desc())
            .limit(1)
        )

    def reject(
        self,
        *,
        tool_call_id: str,
        payload: AgentApprovalDecisionRequest,
        current_user: User,
    ) -> tuple[AgentApproval, AgentApprovalLineage, AgentToolCall, AgentApprovalMutationLog]:
        lineage, call, approval, run, lineage_lock_wait_ms = self._lock_context(
            tool_call_id=tool_call_id,
            payload=payload,
            action="reject",
        )
        self.policy_manager.require_run_access(run=run, current_user=current_user)
        self.policy_manager.require_approval_permissions(approval=approval, current_user=current_user)
        try:
            self._validate_pending_immutable(approval=approval, payload=payload)
            self._expire_if_needed(
                approval=approval,
                lineage=lineage,
                call=call,
                run=run,
                lineage_lock_wait_ms=lineage_lock_wait_ms,
            )
            self._validate_call_approvable(call)
        except HTTPException as exc:
            self._record_decision_conflict(
                action="reject",
                run=run,
                call=call,
                lineage=lineage,
                approval=approval,
                payload=payload,
                error_code=_error_code(exc),
            )
            raise

        now = _utcnow()
        from_status = approval.approval_status
        approval.approval_status = "rejected"
        approval.decided_by = current_user.id
        approval.decided_at = now
        approval.decision_reason = payload.reason
        lineage.status = "rejected"
        lineage.updated_at = now
        call.status = "manual_intervention"
        call.error_code = "approval_rejected"
        call.error_message = payload.reason or "Approval rejected"

        mutation = self._add_mutation(
            approval=approval,
            lineage=lineage,
            mutation_type="reject",
            from_status=from_status,
            to_status="rejected",
            actor_user_id=current_user.id,
            reason=payload.reason,
            details_json={"lineage_lock_wait_ms": lineage_lock_wait_ms},
        )
        from app.services.agent_runtime_service import AgentRuntimeService

        AgentRuntimeService(self.db).append_event(
            run,
            "approval.rejected",
            {
                "tool_call_id": call.tool_call_id,
                "approval_id": approval.approval_id,
                "approval_lineage_id": lineage.approval_lineage_id,
                "approval_epoch": approval.approval_epoch,
            },
            commit=False,
        )
        self._block_queue(call, error_code="approval_rejected")
        self.db.commit()
        self.db.refresh(approval)
        self.db.refresh(lineage)
        self.db.refresh(call)
        self.db.refresh(mutation)
        return approval, lineage, call, mutation

    def supersede_with_replacement(
        self,
        *,
        tool_call_id: str,
        replacement_payload: AgentToolCallCreateRequest,
        current_user: User,
        reason: str | None = None,
    ) -> tuple[AgentApproval, AgentApprovalLineage, AgentToolCall, AgentApproval, AgentApprovalMutationLog, AgentApprovalMutationLog]:
        old_call = self.db.scalar(
            select(AgentToolCall).where(AgentToolCall.tool_call_id == tool_call_id).with_for_update()
        )
        if old_call is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent tool call not found")
        if old_call.approval_lineage_id is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "tool_call_not_approvable"})
        lineage_lock_started_at = perf_counter()
        lineage = self.db.scalar(
            select(AgentApprovalLineage)
            .where(AgentApprovalLineage.approval_lineage_id == old_call.approval_lineage_id)
            .with_for_update()
        )
        lineage_lock_wait_ms = _elapsed_ms(lineage_lock_started_at)
        if lineage is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent approval lineage not found")
        old_approval = self.db.scalar(
            select(AgentApproval)
            .where(
                AgentApproval.approval_lineage_id == lineage.approval_lineage_id,
                AgentApproval.approval_epoch == lineage.current_epoch,
                AgentApproval.approval_status == "pending",
            )
            .with_for_update()
        )
        if old_approval is None or old_approval.tool_call_id != old_call.tool_call_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "approval_stale_or_superseded"})
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == old_call.run_id).with_for_update())
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
        if replacement_payload.run_id != run.run_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"code": "replacement_run_mismatch"})
        self.policy_manager.require_run_access(run=run, current_user=current_user)
        if old_call.status in SUPERSEDE_BLOCKED_TOOL_CALL_STATUSES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "cannot_supersede_executing_call"})

        now = _utcnow()
        next_epoch = lineage.current_epoch + 1
        replacement_call = self._create_replacement_tool_call(
            run=run,
            old_call=old_call,
            payload=replacement_payload,
            current_user=current_user,
            next_epoch=next_epoch,
        )

        old_status = old_approval.approval_status
        old_approval.approval_status = "superseded"
        old_approval.decided_by = current_user.id
        old_approval.decided_at = now
        old_approval.decision_reason = reason or "replacement_tool_call_created"
        old_call.status = "obsolete"
        old_call.error_code = "approval_superseded"
        old_call.error_message = reason or "Approval superseded by replacement tool call"

        lineage.tool_call_id = replacement_call.tool_call_id
        lineage.current_epoch = next_epoch
        lineage.status = "pending"
        lineage.immutable_input_hash = replacement_call.input_hash
        lineage.runtime_snapshot_id = replacement_call.runtime_snapshot_id
        lineage.resource_scope_hash = replacement_call.approval_scope_hash or replacement_call.input_hash
        lineage.updated_at = now

        replacement_approval = AgentApproval(
            approval_id=f"agent-appr-{uuid.uuid4().hex}",
            approval_lineage_id=lineage.approval_lineage_id,
            approval_epoch=next_epoch,
            run_id=run.run_id,
            tool_call_id=replacement_call.tool_call_id,
            project_id=run.project_id,
            approval_status="pending",
            requested_by=current_user.id,
            input_hash=replacement_call.input_hash,
            runtime_snapshot_id=replacement_call.runtime_snapshot_id,
            resource_scope_hash=replacement_call.approval_scope_hash or replacement_call.input_hash,
            approval_reason=reason or "replacement_tool_call_requires_approval",
            required_permissions_json=list(replacement_call.required_permissions_json),
            created_at=now,
            updated_at=now,
        )
        self.db.add(replacement_approval)

        supersede_mutation = self._add_mutation(
            approval=old_approval,
            lineage=lineage,
            mutation_type="supersede",
            from_status=old_status,
            to_status="superseded",
            actor_user_id=current_user.id,
            reason=reason,
            details_json={
                "replacement_tool_call_id": replacement_call.tool_call_id,
                "lineage_lock_wait_ms": lineage_lock_wait_ms,
            },
        )
        create_mutation = self._add_mutation(
            approval=replacement_approval,
            lineage=lineage,
            mutation_type="create_replacement",
            from_status=None,
            to_status="pending",
            actor_user_id=current_user.id,
            reason=reason,
            details_json={
                "superseded_tool_call_id": old_call.tool_call_id,
                "lineage_lock_wait_ms": lineage_lock_wait_ms,
            },
        )
        self._block_queue(old_call, error_code="approval_superseded")
        from app.services.agent_runtime_service import AgentRuntimeService

        runtime = AgentRuntimeService(self.db)
        runtime.append_event(
            run,
            "approval.superseded",
            {
                "tool_call_id": old_call.tool_call_id,
                "approval_id": old_approval.approval_id,
                "approval_lineage_id": lineage.approval_lineage_id,
                "approval_epoch": old_approval.approval_epoch,
                "replacement_tool_call_id": replacement_call.tool_call_id,
                "replacement_approval_epoch": next_epoch,
            },
            commit=False,
        )
        runtime.append_event(
            run,
            "approval.created",
            {
                "tool_call_id": replacement_call.tool_call_id,
                "approval_id": replacement_approval.approval_id,
                "approval_lineage_id": lineage.approval_lineage_id,
                "approval_epoch": replacement_approval.approval_epoch,
                "replacement_for_tool_call_id": old_call.tool_call_id,
            },
            commit=False,
        )
        self.db.commit()
        for item in [old_approval, lineage, replacement_call, replacement_approval, supersede_mutation, create_mutation]:
            self.db.refresh(item)
        return old_approval, lineage, replacement_call, replacement_approval, supersede_mutation, create_mutation

    def _create_replacement_tool_call(
        self,
        *,
        run: AgentRun,
        old_call: AgentToolCall,
        payload: AgentToolCallCreateRequest,
        current_user: User,
        next_epoch: int,
    ) -> AgentToolCall:
        spec = self.tool_registry.get(payload.tool_name)
        resolved = self.tool_policy_resolver.resolve(spec=spec, evidence_refs=payload.evidence_refs)
        max_attempt = self.db.scalar(
            select(func.max(AgentToolCall.attempt_index)).where(
                AgentToolCall.run_id == run.run_id,
                AgentToolCall.step_index == payload.step_index,
            )
        ) or 0
        attempt_index = max(max_attempt + 1, old_call.attempt_index + 1, payload.attempt_index)
        input_hash = request_fingerprint(payload.input)
        contract = spec.backend_contract
        policy_evidence_refs, audit_evidence_refs, evidence_summary = EvidenceRefResolver().split_policy_and_audit_refs(
            payload.evidence_refs
        )
        idempotency_key = payload.idempotency_key or request_fingerprint({
            "run_id": run.run_id,
            "step_index": payload.step_index,
            "attempt_index": attempt_index,
            "tool_name": payload.tool_name,
            "input": payload.input,
            "replacement_for": old_call.tool_call_id,
        })
        replacement = AgentToolCall(
            tool_call_id=f"agent-tool-{uuid.uuid4().hex}",
            run_id=run.run_id,
            step_index=payload.step_index,
            attempt_index=attempt_index,
            runtime_snapshot_id=run.runtime_snapshot_id,
            tool_name=spec.name,
            tool_version=spec.version,
            schema_hash=spec.schema_hash,
            manifest_hash=spec.manifest_hash,
            idempotency_scope=run.run_id,
            idempotency_key=idempotency_key,
            base_side_effect_class=spec.side_effect_class,
            resolved_side_effect_class=resolved.resolved_side_effect_class,
            base_replay_policy=spec.replay_policy,
            resolved_replay_policy=resolved.resolved_replay_policy,
            policy_reason_json={
                **resolved.policy_reason,
                "replacement_for_tool_call_id": old_call.tool_call_id,
            },
            status="planned",
            effect_submission_state="none",
            input_hash=input_hash,
            input_json_redacted=mask_sensitive(payload.input),
            evidence_refs_json=[mask_sensitive(dict(item)) for item in payload.evidence_refs],
            policy_evidence_refs_json=policy_evidence_refs,
            audit_evidence_refs_json=audit_evidence_refs,
            evidence_mutability_summary_json=evidence_summary,
            decision_context_build_id=payload.decision_context_build_id,
            permission_snapshot_json={
                "user_id": current_user.id,
                "project_id": run.project_id,
                "required_permissions": list(spec.required_permissions),
                "captured_at": _utcnow().isoformat(),
                "audit_only": True,
                "replacement_for_tool_call_id": old_call.tool_call_id,
            },
            required_permissions_json=list(spec.required_permissions),
            approval_required=True,
            approval_scope_hash=request_fingerprint({
                "run_id": run.run_id,
                "tool_name": spec.name,
                "input_hash": input_hash,
            }),
            approval_lineage_id=old_call.approval_lineage_id,
            approval_epoch=next_epoch,
            backend_name=contract.backend_name if contract else None,
            backend_operation=contract.backend_operation if contract else None,
            backend_contract_version=contract.backend_contract_version if contract else None,
            backend_request_schema_hash=contract.request_schema_hash if contract else None,
            backend_output_schema_hash=contract.output_schema_hash if contract else None,
            reconcile_contract_version=contract.reconcile_contract_version if contract else None,
            result_adapter_version=contract.result_adapter_version if contract else None,
            backend_effect_capability=contract.effect_capability if contract else None,
        )
        self.db.add(replacement)
        self.db.flush()
        from app.services.agent_runtime_service import AgentRuntimeService

        AgentRuntimeService(self.db).append_event(
            run,
            "tool.planned",
            {
                "tool_call_id": replacement.tool_call_id,
                "tool_name": replacement.tool_name,
                "replacement_for_tool_call_id": old_call.tool_call_id,
            },
            commit=False,
        )
        EvidenceWatchService(self.db).register_watches(
            run=run,
            evidence_refs=payload.evidence_refs,
            tool_call_id=replacement.tool_call_id,
            commit=False,
        )
        return replacement

    def expire_approval(self, *, approval_id: str, now: datetime | None = None) -> AgentApproval | None:
        approval = self.db.scalar(
            select(AgentApproval)
            .where(AgentApproval.approval_id == approval_id)
            .with_for_update()
        )
        if approval is None or approval.approval_status != "pending":
            return approval
        current = now or _utcnow()
        if approval.expires_at is None or approval.expires_at > current:
            return approval
        lineage_lock_started_at = perf_counter()
        lineage = self.db.scalar(
            select(AgentApprovalLineage)
            .where(AgentApprovalLineage.approval_lineage_id == approval.approval_lineage_id)
            .with_for_update()
        )
        lineage_lock_wait_ms = _elapsed_ms(lineage_lock_started_at)
        call = self.db.scalar(
            select(AgentToolCall)
            .where(AgentToolCall.tool_call_id == approval.tool_call_id)
            .with_for_update()
        )
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == approval.run_id).with_for_update())
        if lineage is None or call is None or run is None:
            return approval
        self._mark_expired_locked(
            approval=approval,
            lineage=lineage,
            call=call,
            run=run,
            current=current,
            lineage_lock_wait_ms=lineage_lock_wait_ms,
        )
        self.db.commit()
        self.db.refresh(approval)
        return approval

    def _lock_context(
        self,
        *,
        tool_call_id: str,
        payload: AgentApprovalDecisionRequest,
        action: str,
    ) -> tuple[AgentApprovalLineage, AgentToolCall, AgentApproval, AgentRun, int]:
        lineage_lock_started_at = perf_counter()
        lineage = self.db.scalar(
            select(AgentApprovalLineage)
            .where(AgentApprovalLineage.approval_lineage_id == payload.approval_lineage_id)
            .with_for_update()
        )
        lineage_lock_wait_ms = _elapsed_ms(lineage_lock_started_at)
        if lineage is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent approval lineage not found")
        call = self.db.scalar(
            select(AgentToolCall).where(AgentToolCall.tool_call_id == tool_call_id).with_for_update()
        )
        if call is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent tool call not found")
        if call.approval_lineage_id != lineage.approval_lineage_id or lineage.tool_call_id != call.tool_call_id:
            self._record_decision_conflict(
                action=action,
                run=self._load_run_for_conflict(call),
                call=call,
                lineage=lineage,
                approval=None,
                payload=payload,
                error_code="approval_stale_or_superseded",
            )
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "approval_stale_or_superseded"})
        if payload.approval_epoch != lineage.current_epoch or payload.approval_epoch != call.approval_epoch:
            self._record_decision_conflict(
                action=action,
                run=self._load_run_for_conflict(call),
                call=call,
                lineage=lineage,
                approval=None,
                payload=payload,
                error_code="approval_epoch_conflict",
            )
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "approval_epoch_conflict"})
        approval = self.db.scalar(
            select(AgentApproval)
            .where(
                AgentApproval.approval_lineage_id == lineage.approval_lineage_id,
                AgentApproval.approval_epoch == payload.approval_epoch,
            )
            .with_for_update()
        )
        if approval is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent approval not found")
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == call.run_id).with_for_update())
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
        return lineage, call, approval, run, lineage_lock_wait_ms

    def _load_run_for_conflict(self, call: AgentToolCall) -> AgentRun | None:
        return self.db.scalar(select(AgentRun).where(AgentRun.run_id == call.run_id).with_for_update())

    def _record_decision_conflict(
        self,
        *,
        action: str,
        run: AgentRun | None,
        call: AgentToolCall,
        lineage: AgentApprovalLineage,
        approval: AgentApproval | None,
        payload: AgentApprovalDecisionRequest,
        error_code: str,
    ) -> None:
        if run is None:
            return
        from app.services.agent_runtime_service import AgentRuntimeService

        AgentRuntimeService(self.db).append_event(
            run,
            f"approval.{action}_conflict",
            {
                "tool_call_id": call.tool_call_id,
                "approval_id": approval.approval_id if approval else None,
                "approval_lineage_id": lineage.approval_lineage_id,
                "approval_epoch": payload.approval_epoch,
                "current_epoch": lineage.current_epoch,
                "error_code": error_code,
            },
            commit=False,
        )
        self.db.commit()

    def _validate_pending_immutable(self, *, approval: AgentApproval, payload: AgentApprovalDecisionRequest) -> None:
        if approval.approval_status != "pending":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "approval_stale_or_superseded"})
        if approval.input_hash != payload.input_hash:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "approval_input_changed"})
        if (
            approval.runtime_snapshot_id != payload.runtime_snapshot_id
            or approval.resource_scope_hash != payload.resource_scope_hash
            or approval.approval_lineage_id != payload.approval_lineage_id
            or approval.approval_epoch != payload.approval_epoch
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "approval_stale_or_superseded"})

    def _expire_if_needed(
        self,
        *,
        approval: AgentApproval,
        lineage: AgentApprovalLineage,
        call: AgentToolCall,
        run: AgentRun,
        lineage_lock_wait_ms: int,
    ) -> None:
        current = _utcnow()
        if approval.expires_at is None or approval.expires_at > current:
            return
        self._mark_expired_locked(
            approval=approval,
            lineage=lineage,
            call=call,
            run=run,
            current=current,
            lineage_lock_wait_ms=lineage_lock_wait_ms,
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "approval_stale_or_superseded"})

    def _mark_expired_locked(
        self,
        *,
        approval: AgentApproval,
        lineage: AgentApprovalLineage,
        call: AgentToolCall,
        run: AgentRun,
        current: datetime,
        lineage_lock_wait_ms: int,
    ) -> None:
        if approval.approval_status != "pending":
            return
        from_status = approval.approval_status
        approval.approval_status = "expired"
        approval.decided_at = current
        lineage.status = "expired"
        lineage.updated_at = current
        call.status = "manual_intervention"
        call.error_code = "approval_expired"
        self._add_mutation(
            approval=approval,
            lineage=lineage,
            mutation_type="expire",
            from_status=from_status,
            to_status="expired",
            actor_user_id=None,
            reason="approval_expired",
            details_json={"lineage_lock_wait_ms": lineage_lock_wait_ms},
        )
        from app.services.agent_runtime_service import AgentRuntimeService

        AgentRuntimeService(self.db).append_event(
            run,
            "approval.expired",
            {
                "tool_call_id": call.tool_call_id,
                "approval_id": approval.approval_id,
                "approval_lineage_id": lineage.approval_lineage_id,
                "approval_epoch": approval.approval_epoch,
            },
            commit=False,
        )
        self._block_queue(call, error_code="approval_expired")

    def _validate_call_approvable(self, call: AgentToolCall) -> None:
        if call.status not in APPROVABLE_TOOL_CALL_STATUSES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "tool_call_not_approvable"})

    def _release_or_enqueue(self, call: AgentToolCall) -> None:
        item = self.db.scalar(
            select(AgentWorkerQueue)
            .where(AgentWorkerQueue.tool_call_id == call.tool_call_id)
            .order_by(AgentWorkerQueue.created_at.desc())
            .with_for_update()
            .limit(1)
        )
        if item is None:
            from app.services.agent_runtime_service import AgentWorkerQueueService

            AgentWorkerQueueService(self.db).enqueue_tool_call(call, commit=False)
            return
        if item.status in {"blocked_approval", "failed"} and item.last_error_code in {
            "approval_required_before_execution",
            "approval_rejected",
            "approval_expired",
            None,
        }:
            item.status = "queued"
            item.last_error_code = None
            item.lease_owner = None
            item.lease_expires_at = None
            call.status = "planned"

    def _block_queue(self, call: AgentToolCall, *, error_code: str) -> None:
        for item in self.db.scalars(
            select(AgentWorkerQueue).where(
                AgentWorkerQueue.tool_call_id == call.tool_call_id,
                AgentWorkerQueue.status.in_(["queued", "leased", "blocked_approval"]),
            )
        ).all():
            item.status = "blocked_approval"
            item.last_error_code = error_code
            item.lease_owner = None
            item.lease_expires_at = None

    def _add_mutation(
        self,
        *,
        approval: AgentApproval,
        lineage: AgentApprovalLineage,
        mutation_type: str,
        from_status: str | None,
        to_status: str,
        actor_user_id: int | None,
        reason: str | None,
        details_json: dict[str, Any] | None = None,
    ) -> AgentApprovalMutationLog:
        mutation = AgentApprovalMutationLog(
            approval_lineage_id=lineage.approval_lineage_id,
            approval_id=approval.approval_id,
            tool_call_id=approval.tool_call_id,
            run_id=approval.run_id,
            mutation_type=mutation_type,
            from_status=from_status,
            to_status=to_status,
            actor_user_id=actor_user_id,
            reason=reason,
            details_json=details_json,
        )
        self.db.add(mutation)
        return mutation


class ApprovalExpireScanner:
    def __init__(self, db: Session):
        self.db = db

    def audit(self, *, project_id: int | None = None, now: datetime | None = None) -> dict[str, Any]:
        current = now or _utcnow()
        statement = (
            select(AgentApproval)
            .where(
                AgentApproval.approval_status == "pending",
                AgentApproval.expires_at.is_not(None),
                AgentApproval.expires_at <= current,
            )
            .order_by(AgentApproval.approval_lineage_id.asc(), AgentApproval.expires_at.asc())
        )
        if project_id is not None:
            statement = statement.where(AgentApproval.project_id == project_id)
        approvals = list(self.db.scalars(statement).all())
        lineage_counts: dict[str, int] = {}
        for approval in approvals:
            lineage_counts[approval.approval_lineage_id] = lineage_counts.get(approval.approval_lineage_id, 0) + 1
        oldest_due_lag_ms = 0
        if approvals:
            oldest_expires_at = min(approval.expires_at for approval in approvals if approval.expires_at is not None)
            oldest_due_lag_ms = max(0, int((current - oldest_expires_at).total_seconds() * 1000))
        hotspot_lineages = sorted(
            lineage_id for lineage_id, count in lineage_counts.items() if count > 1
        )
        audit = {
            "project_id": project_id,
            "generated_at": current.isoformat(),
            "due_count": len(approvals),
            "candidate_lineage_count": len(lineage_counts),
            "oldest_due_lag_ms": oldest_due_lag_ms,
            "lineage_hotspot_count": len(hotspot_lineages),
            "hotspot_lineage_ids": hotspot_lineages,
            "batch_safe": len(hotspot_lineages) == 0,
            "derived_from": {
                "approval_table": "ai_agent_approvals",
                "mutation_log_table": "ai_agent_approval_mutation_logs",
                "candidate_order": "approval_lineage_id asc, expires_at asc",
                "processing_model": "short transaction per approval lineage",
                "scope": "project" if project_id is not None else "global",
            },
        }
        audit["derived_from"] = {
            field: audit["derived_from"][field]
            for field in APPROVAL_EXPIRE_DERIVED_FROM_FIELDS
        }
        return {field: audit[field] for field in APPROVAL_EXPIRE_AUDIT_FIELDS}

    def expire_due_summary(
        self,
        *,
        limit: int = 100,
        now: datetime | None = None,
        project_id: int | None = None,
    ) -> dict[str, Any]:
        current = now or _utcnow()
        before = self.audit(project_id=project_id, now=current)
        statement = (
            select(AgentApproval)
            .where(
                AgentApproval.approval_status == "pending",
                AgentApproval.expires_at.is_not(None),
                AgentApproval.expires_at <= current,
            )
            .order_by(AgentApproval.approval_lineage_id.asc(), AgentApproval.expires_at.asc())
            .limit(limit)
        )
        if project_id is not None:
            statement = statement.where(AgentApproval.project_id == project_id)
        approvals = list(self.db.scalars(statement).all())
        expired = 0
        attempted = 0
        skipped_duplicate_lineage_count = 0
        seen_lineage_ids: set[str] = set()
        processed_lineage_ids: list[str] = []
        processed_approval_ids: list[str] = []
        guard = ApprovalMutationGuard(self.db)
        for approval in approvals:
            if approval.approval_lineage_id in seen_lineage_ids:
                skipped_duplicate_lineage_count += 1
                continue
            seen_lineage_ids.add(approval.approval_lineage_id)
            attempted += 1
            processed_lineage_ids.append(approval.approval_lineage_id)
            processed_approval_ids.append(approval.approval_id)
            refreshed = guard.expire_approval(approval_id=approval.approval_id, now=current)
            if refreshed is not None and refreshed.approval_status == "expired":
                expired += 1
        after = self.audit(project_id=project_id, now=current)
        lineage_lock_wait_ms = self._sum_lineage_lock_wait_ms(
            approval_ids=processed_approval_ids,
            mutation_type="expire",
        )
        summary = {
            "project_id": project_id,
            "generated_at": current.isoformat(),
            "limit": limit,
            "attempted": attempted,
            "expired": expired,
            "skipped": (attempted - expired) + skipped_duplicate_lineage_count,
            "skipped_duplicate_lineage_count": skipped_duplicate_lineage_count,
            "processed_lineage_ids": processed_lineage_ids,
            "lineage_lock_wait_ms": lineage_lock_wait_ms,
            "lineage_lock_skip_total": 0,
            "due_before": before["due_count"],
            "due_after": after["due_count"],
            "oldest_due_lag_ms_before": before["oldest_due_lag_ms"],
            "oldest_due_lag_ms_after": after["oldest_due_lag_ms"],
            "lineage_hotspot_count_before": before["lineage_hotspot_count"],
            "lineage_hotspot_count_after": after["lineage_hotspot_count"],
            "batch_safe": before["batch_safe"] and after["batch_safe"],
            "derived_from": before["derived_from"],
        }
        summary["derived_from"] = {
            field: summary["derived_from"][field]
            for field in APPROVAL_EXPIRE_DERIVED_FROM_FIELDS
        }
        return {field: summary[field] for field in APPROVAL_EXPIRE_PROCESS_FIELDS}

    def expire_due(self, *, limit: int = 100, now: datetime | None = None) -> int:
        return int(self.expire_due_summary(limit=limit, now=now)["expired"])

    def _sum_lineage_lock_wait_ms(self, *, approval_ids: list[str], mutation_type: str) -> int:
        if not approval_ids:
            return 0
        mutations = list(
            self.db.scalars(
                select(AgentApprovalMutationLog).where(
                    AgentApprovalMutationLog.approval_id.in_(approval_ids),
                    AgentApprovalMutationLog.mutation_type == mutation_type,
                )
            ).all()
        )
        total = 0
        for mutation in mutations:
            details = mutation.details_json or {}
            total += int(details.get("lineage_lock_wait_ms") or 0)
        return total


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _error_code(exc: HTTPException) -> str:
    if isinstance(exc.detail, dict) and exc.detail.get("code"):
        return str(exc.detail["code"])
    return "approval_stale_or_superseded"


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))
