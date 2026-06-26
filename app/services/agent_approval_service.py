from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

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
from app.schemas.agent import AgentApprovalDecisionRequest
from app.services.permission_service import PermissionService


APPROVAL_FINAL_STATUSES = {"approved", "rejected", "expired", "superseded"}
HIGH_RISK_SIDE_EFFECT_CLASSES = {"business_create", "business_update", "destructive", "external_effect"}


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
        if policy_refs and all(ref.get("ref_type") == "memory" for ref in policy_refs):
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

    def approve(
        self,
        *,
        tool_call_id: str,
        payload: AgentApprovalDecisionRequest,
        current_user: User,
    ) -> tuple[AgentApproval, AgentApprovalLineage, AgentToolCall, AgentApprovalMutationLog]:
        lineage, call, approval, run = self._lock_context(tool_call_id=tool_call_id, payload=payload, action="approve")
        self.policy_manager.require_run_access(run=run, current_user=current_user)
        self.policy_manager.require_approval_permissions(approval=approval, current_user=current_user)
        try:
            self._validate_pending_immutable(approval=approval, payload=payload)
            self._validate_not_expired(approval)
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

    def reject(
        self,
        *,
        tool_call_id: str,
        payload: AgentApprovalDecisionRequest,
        current_user: User,
    ) -> tuple[AgentApproval, AgentApprovalLineage, AgentToolCall, AgentApprovalMutationLog]:
        lineage, call, approval, run = self._lock_context(tool_call_id=tool_call_id, payload=payload, action="reject")
        self.policy_manager.require_run_access(run=run, current_user=current_user)
        self.policy_manager.require_approval_permissions(approval=approval, current_user=current_user)
        try:
            self._validate_pending_immutable(approval=approval, payload=payload)
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
        lineage = self.db.scalar(
            select(AgentApprovalLineage)
            .where(AgentApprovalLineage.approval_lineage_id == approval.approval_lineage_id)
            .with_for_update()
        )
        call = self.db.scalar(
            select(AgentToolCall)
            .where(AgentToolCall.tool_call_id == approval.tool_call_id)
            .with_for_update()
        )
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == approval.run_id).with_for_update())
        if lineage is None or call is None or run is None:
            return approval
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
        self.db.commit()
        self.db.refresh(approval)
        return approval

    def _lock_context(
        self,
        *,
        tool_call_id: str,
        payload: AgentApprovalDecisionRequest,
        action: str,
    ) -> tuple[AgentApprovalLineage, AgentToolCall, AgentApproval, AgentRun]:
        lineage = self.db.scalar(
            select(AgentApprovalLineage)
            .where(AgentApprovalLineage.approval_lineage_id == payload.approval_lineage_id)
            .with_for_update()
        )
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
        return lineage, call, approval, run

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
        if (
            approval.input_hash != payload.input_hash
            or approval.runtime_snapshot_id != payload.runtime_snapshot_id
            or approval.resource_scope_hash != payload.resource_scope_hash
            or approval.approval_lineage_id != payload.approval_lineage_id
            or approval.approval_epoch != payload.approval_epoch
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "approval_stale_or_superseded"})

    def _validate_not_expired(self, approval: AgentApproval) -> None:
        if approval.expires_at is not None and approval.expires_at <= _utcnow():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "approval_stale_or_superseded"})

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

    def expire_due(self, *, limit: int = 100, now: datetime | None = None) -> int:
        current = now or _utcnow()
        approvals = list(
            self.db.scalars(
                select(AgentApproval)
                .where(
                    AgentApproval.approval_status == "pending",
                    AgentApproval.expires_at.is_not(None),
                    AgentApproval.expires_at <= current,
                )
                .order_by(AgentApproval.approval_lineage_id.asc(), AgentApproval.expires_at.asc())
                .limit(limit)
            ).all()
        )
        expired = 0
        guard = ApprovalMutationGuard(self.db)
        for approval in approvals:
            refreshed = guard.expire_approval(approval_id=approval.approval_id, now=current)
            if refreshed is not None and refreshed.approval_status == "expired":
                expired += 1
        return expired


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _error_code(exc: HTTPException) -> str:
    if isinstance(exc.detail, dict) and exc.detail.get("code"):
        return str(exc.detail["code"])
    return "approval_stale_or_superseded"
