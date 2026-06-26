from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.sensitive_data import mask_sensitive, request_fingerprint
from app.models.agent import (
    AgentBackendContract,
    AgentCheckpoint,
    AgentEvent,
    AgentOutbox,
    AgentRun,
    AgentRuntimeSnapshot,
    AgentToolCall,
    AgentWorkerQueue,
)
from app.models.user import User
from app.schemas.agent import AgentRunCreateRequest, AgentToolCallCreateRequest
from app.services.agent_approval_service import ApprovalService, PolicyManager
from app.services.agent_loop_service import EvidenceRefResolver, EvidenceWatchService
from app.services.agent_tool_service import AgentToolBackend, SAFE_SIDE_EFFECT_CLASSES, ToolPolicyResolver, ToolRegistry
from app.services.permission_service import PermissionService


RUN_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
RUN_STATUSES = ["queued", "running", "paused", "completed", "failed", "cancelled", "migration_blocked", "needs_human"]
TOOL_CALL_STATUSES = [
    "planned",
    "leased",
    "running_pre_effect",
    "effect_sent",
    "uncertain",
    "reconciling",
    "succeeded",
    "failed",
    "failed_retryable",
    "obsolete",
    "needs_migration",
    "manual_intervention",
]
EFFECT_SUBMISSION_STATES = [
    "none",
    "send_intent_recorded",
    "transport_sent_observed",
    "backend_accepted",
    "effect_committed",
    "unknown",
]
BACKEND_EFFECT_CAPABILITIES = [
    "receipt_first",
    "idempotency_index_only",
    "legacy_reconcile_only",
    "legacy_no_receipt",
]


class AgentRuntimeService:
    def __init__(self, db: Session):
        self.db = db
        self.permission_service = PermissionService(db)
        self.tool_registry = ToolRegistry()

    def capabilities(self) -> dict[str, Any]:
        return {
            "run_statuses": RUN_STATUSES,
            "tool_call_statuses": TOOL_CALL_STATUSES,
            "effect_submission_states": EFFECT_SUBMISSION_STATES,
            "backend_effect_capabilities": BACKEND_EFFECT_CAPABILITIES,
            "tools": self.tool_registry.registry_json(),
        }

    def ensure_backend_contracts(self, *, commit: bool = True) -> None:
        self._seed_backend_contracts()
        if commit:
            self.db.commit()
        else:
            self.db.flush()

    def create_run(self, *, payload: AgentRunCreateRequest, current_user: User) -> AgentRun:
        self.permission_service.require_project_access(current_user, payload.project_id)
        snapshot = self._get_or_create_snapshot(project_id=payload.project_id, current_user=current_user)
        now = _utcnow()
        run = AgentRun(
            run_id=f"agent-run-{uuid.uuid4().hex}",
            project_id=payload.project_id,
            user_id=current_user.id,
            conversation_id=payload.conversation_id,
            intent=payload.intent,
            status="queued",
            current_iteration=0,
            current_step_index=0,
            max_iterations=payload.max_iterations,
            runtime_snapshot_id=snapshot.snapshot_id,
            last_event_sequence=0,
            created_at=now,
            updated_at=now,
        )
        self.db.add(run)
        self.db.flush()
        self.append_event(run, "run.queued", {"intent": payload.intent}, commit=False)
        run.status = "running"
        run.started_at = now
        self.append_event(run, "run.started", {"runtime_snapshot_id": snapshot.snapshot_id}, commit=False)
        checkpoint = self.create_checkpoint(run, commit=False)
        run.last_checkpoint_id = checkpoint.id
        if payload.auto_complete:
            self.complete_run(run, {"message": "Agent runtime skeleton completed without tool calls."}, commit=False)
        self.db.commit()
        self.db.refresh(run)
        return run

    def get_run(self, *, run_id: str, current_user: User) -> AgentRun:
        run = self._get_run_or_404(run_id)
        self.permission_service.require_project_access(current_user, run.project_id)
        return run

    def cancel_run(self, *, run_id: str, current_user: User) -> AgentRun:
        run = self._get_run_or_404(run_id, for_update=True)
        self.permission_service.require_project_access(current_user, run.project_id)
        if run.status in RUN_TERMINAL_STATUSES:
            return run
        run.status = "cancelled"
        run.completed_at = _utcnow()
        self.append_event(run, "run.cancelled", {"status": run.status}, commit=False)
        self.db.commit()
        self.db.refresh(run)
        return run

    def get_snapshot(self, *, snapshot_id: str, current_user: User) -> AgentRuntimeSnapshot:
        snapshot = self.db.scalar(
            select(AgentRuntimeSnapshot).where(AgentRuntimeSnapshot.snapshot_id == snapshot_id)
        )
        if snapshot is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent runtime snapshot 不存在")
        self.permission_service.require_project_access(current_user, snapshot.project_id)
        return snapshot

    def list_events(self, *, run_id: str, after_sequence: int) -> tuple[list[AgentEvent], AgentRun]:
        run = self._get_run_or_404(run_id)
        events = list(self.db.scalars(
            select(AgentEvent)
            .where(AgentEvent.run_id == run_id, AgentEvent.event_seq > after_sequence)
            .order_by(AgentEvent.event_seq)
        ).all())
        return events, run

    def append_event(
        self,
        run: AgentRun,
        event_type: str,
        payload: dict[str, Any],
        *,
        commit: bool = True,
    ) -> AgentEvent:
        locked_run = self.db.scalar(
            select(AgentRun).where(AgentRun.id == run.id).with_for_update()
        )
        if locked_run is not None:
            run = locked_run
        event_seq = (run.last_event_sequence or 0) + 1
        event = AgentEvent(
            run_id=run.run_id,
            event_seq=event_seq,
            event_type=event_type,
            payload_json={
                "schema_version": 1,
                "run_id": run.run_id,
                "project_id": run.project_id,
                "event_seq": event_seq,
                "event_type": event_type,
                "occurred_at": _utcnow().isoformat(),
                **mask_sensitive(payload),
            },
        )
        run.last_event_sequence = event_seq
        self.db.add(event)
        self.db.flush()
        self.db.add(AgentOutbox(event_id=event.id, status="pending"))
        if commit:
            self.db.commit()
            self.db.refresh(event)
        else:
            self.db.flush()
        return event

    def complete_run(self, run: AgentRun, result: dict[str, Any], *, commit: bool = True) -> AgentRun:
        run.status = "completed"
        run.result_json = mask_sensitive(result)
        run.completed_at = _utcnow()
        self.append_event(run, "run.completed", {"result": run.result_json}, commit=False)
        if commit:
            self.db.commit()
            self.db.refresh(run)
        return run

    def create_checkpoint(self, run: AgentRun, *, commit: bool = True) -> AgentCheckpoint:
        checkpoint_seq = (
            self.db.scalar(
                select(func.max(AgentCheckpoint.checkpoint_seq)).where(AgentCheckpoint.run_id == run.run_id)
            )
            or 0
        ) + 1
        checkpoint = AgentCheckpoint(
            run_id=run.run_id,
            checkpoint_seq=checkpoint_seq,
            runtime_snapshot_id=run.runtime_snapshot_id,
            iteration=run.current_iteration,
            current_step_index=run.current_step_index,
            active_plan_summary_json={"intent": run.intent},
            active_draft_summary_json=None,
            last_failure_summary_json=None,
            recent_tool_call_ids_json=[],
            pending_approval_tool_call_ids_json=[],
            freshness_metadata_json={"created_from": "runtime_skeleton"},
        )
        self.db.add(checkpoint)
        if commit:
            self.db.commit()
            self.db.refresh(checkpoint)
        else:
            self.db.flush()
        return checkpoint

    def _get_or_create_snapshot(self, *, project_id: int, current_user: User) -> AgentRuntimeSnapshot:
        registry_json = self.tool_registry.registry_json()
        runtime_hash = self.tool_registry.runtime_hash()
        existing = self.db.scalar(
            select(AgentRuntimeSnapshot).where(
                AgentRuntimeSnapshot.project_id == project_id,
                AgentRuntimeSnapshot.runtime_hash == runtime_hash,
            )
        )
        if existing is not None:
            return existing
        snapshot = AgentRuntimeSnapshot(
            snapshot_id=f"agent-snap-{uuid.uuid4().hex}",
            project_id=project_id,
            created_by=current_user.id,
            runtime_hash=runtime_hash,
            tool_registry_hash=self.tool_registry.registry_hash(),
            manifest_bundle_hash=self.tool_registry.manifest_bundle_hash(),
            prompt_bundle_hash=request_fingerprint({"prompt_bundle": "agent-runtime-v1"}),
            policy_version_hash=request_fingerprint({"policy": "agent-policy-v1"}),
            tools_json=registry_json,
            manifests_json={"tools": {item["name"]: item for item in registry_json}},
            adapters_json={"adapter_bundle": "agent-adapters-v1"},
            policies_json={"policy_bundle": "agent-policy-v1"},
        )
        self.db.add(snapshot)
        self._seed_backend_contracts()
        self.db.flush()
        return snapshot

    def _seed_backend_contracts(self) -> None:
        for spec in self.tool_registry.list_specs():
            contract = spec.backend_contract
            if contract is None:
                continue
            existing = self.db.scalar(
                select(AgentBackendContract).where(
                    AgentBackendContract.backend_name == contract.backend_name,
                    AgentBackendContract.backend_operation == contract.backend_operation,
                    AgentBackendContract.backend_contract_version == contract.backend_contract_version,
                )
            )
            if existing is not None:
                continue
            self.db.add(AgentBackendContract(
                backend_name=contract.backend_name,
                backend_operation=contract.backend_operation,
                backend_contract_version=contract.backend_contract_version,
                request_schema_hash=contract.request_schema_hash,
                output_schema_hash=contract.output_schema_hash,
                reconcile_contract_version=contract.reconcile_contract_version,
                result_adapter_version=contract.result_adapter_version,
                effect_capability=contract.effect_capability,
                compatibility_status=contract.compatibility_status,
                owner_team=contract.owner_team,
            ))

    def _get_run_or_404(self, run_id: str, *, for_update: bool = False) -> AgentRun:
        statement = select(AgentRun).where(AgentRun.run_id == run_id)
        if for_update:
            statement = statement.with_for_update()
        run = self.db.scalar(statement)
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run 不存在")
        return run


class ExecutionLedgerService:
    def __init__(self, db: Session):
        self.db = db
        self.tool_registry = ToolRegistry()
        self.policy_resolver = ToolPolicyResolver()
        self.permission_service = PermissionService(db)

    def create_tool_call(
        self,
        *,
        payload: AgentToolCallCreateRequest,
        current_user: User,
        enqueue: bool = True,
    ) -> AgentToolCall:
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == payload.run_id).with_for_update())
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run 不存在")
        self.permission_service.require_project_access(current_user, run.project_id)
        if run.status == "cancelled":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "tool_call_obsolete"})
        if run.status == "migration_blocked":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "run_migration_blocked"})

        spec = self.tool_registry.get(payload.tool_name)
        resolved = self.policy_resolver.resolve(spec=spec, evidence_refs=payload.evidence_refs)
        idempotency_key = payload.idempotency_key or request_fingerprint({
            "run_id": payload.run_id,
            "step_index": payload.step_index,
            "attempt_index": payload.attempt_index,
            "tool_name": payload.tool_name,
            "input": payload.input,
        })
        existing = self.db.scalar(
            select(AgentToolCall).where(
                AgentToolCall.idempotency_scope == payload.run_id,
                AgentToolCall.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            self._record_duplicate_blocked(run=run, existing=existing, idempotency_key=idempotency_key)
            return existing

        permission_snapshot = {
            "user_id": current_user.id,
            "project_id": run.project_id,
            "required_permissions": list(spec.required_permissions),
            "captured_at": _utcnow().isoformat(),
            "audit_only": True,
        }
        contract = spec.backend_contract
        policy_evidence_refs, audit_evidence_refs, evidence_summary = EvidenceRefResolver().split_policy_and_audit_refs(
            payload.evidence_refs
        )
        call = AgentToolCall(
            tool_call_id=f"agent-tool-{uuid.uuid4().hex}",
            run_id=run.run_id,
            step_index=payload.step_index,
            attempt_index=payload.attempt_index,
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
            policy_reason_json=resolved.policy_reason,
            status="planned",
            effect_submission_state="none",
            input_hash=request_fingerprint(payload.input),
            input_json_redacted=mask_sensitive(payload.input),
            evidence_refs_json=copy_evidence_refs(payload.evidence_refs),
            policy_evidence_refs_json=policy_evidence_refs,
            audit_evidence_refs_json=audit_evidence_refs,
            evidence_mutability_summary_json=evidence_summary,
            decision_context_build_id=payload.decision_context_build_id,
            permission_snapshot_json=permission_snapshot,
            required_permissions_json=list(spec.required_permissions),
            approval_required=resolved.approval_required,
            approval_scope_hash=request_fingerprint({
                "run_id": run.run_id,
                "tool_name": spec.name,
                "input_hash": request_fingerprint(payload.input),
            }),
            backend_name=contract.backend_name if contract else None,
            backend_operation=contract.backend_operation if contract else None,
            backend_contract_version=contract.backend_contract_version if contract else None,
            backend_request_schema_hash=contract.request_schema_hash if contract else None,
            backend_output_schema_hash=contract.output_schema_hash if contract else None,
            reconcile_contract_version=contract.reconcile_contract_version if contract else None,
            result_adapter_version=contract.result_adapter_version if contract else None,
            backend_effect_capability=contract.effect_capability if contract else None,
        )
        self.db.add(call)
        self.db.flush()
        runtime = AgentRuntimeService(self.db)
        runtime.append_event(run, "tool.planned", {"tool_call_id": call.tool_call_id, "tool_name": call.tool_name}, commit=False)
        EvidenceWatchService(self.db).register_watches(
            run=run,
            evidence_refs=payload.evidence_refs,
            tool_call_id=call.tool_call_id,
            commit=False,
        )
        if call.approval_required:
            ApprovalService(self.db).create_pending_approval(
                call=call,
                run=run,
                current_user=current_user,
                commit=False,
            )
        if enqueue and not call.approval_required:
            AgentWorkerQueueService(self.db).enqueue_tool_call(call, commit=False)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.db.scalar(
                select(AgentToolCall).where(
                    AgentToolCall.idempotency_scope == payload.run_id,
                    AgentToolCall.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                self._record_duplicate_blocked(run=run, existing=existing, idempotency_key=idempotency_key)
                return existing
            raise
        self.db.refresh(call)
        return call

    def _record_duplicate_blocked(self, *, run: AgentRun, existing: AgentToolCall, idempotency_key: str) -> None:
        AgentRuntimeService(self.db).append_event(
            run,
            "tool.duplicate_blocked",
            {
                "tool_call_id": existing.tool_call_id,
                "tool_name": existing.tool_name,
                "idempotency_scope": run.run_id,
                "idempotency_key": idempotency_key,
            },
            commit=True,
        )

    def get_tool_call(self, *, tool_call_id: str, current_user: User) -> AgentToolCall:
        call = self.db.scalar(select(AgentToolCall).where(AgentToolCall.tool_call_id == tool_call_id))
        if call is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent tool call 不存在")
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == call.run_id))
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run 不存在")
        self.permission_service.require_project_access(current_user, run.project_id)
        return call


class AgentWorkerQueueService:
    def __init__(self, db: Session):
        self.db = db

    def enqueue_tool_call(self, call: AgentToolCall, *, commit: bool = True, priority: int = 100) -> AgentWorkerQueue:
        item = AgentWorkerQueue(
            queue_id=f"agent-queue-{uuid.uuid4().hex}",
            run_id=call.run_id,
            tool_call_id=call.tool_call_id,
            status="queued",
            priority=priority,
            available_at=_utcnow(),
        )
        self.db.add(item)
        if commit:
            self.db.commit()
            self.db.refresh(item)
        else:
            self.db.flush()
        return item

    def claim_next(self, *, worker_id: str, lease_seconds: int = 60) -> AgentWorkerQueue | None:
        now = _utcnow()
        item = self.db.scalar(
            select(AgentWorkerQueue)
            .where(
                AgentWorkerQueue.status == "queued",
                AgentWorkerQueue.available_at <= now,
            )
            .order_by(AgentWorkerQueue.priority.asc(), AgentWorkerQueue.created_at.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if item is None:
            return None
        call = self.db.scalar(select(AgentToolCall).where(AgentToolCall.tool_call_id == item.tool_call_id).with_for_update())
        if call is not None and call.approval_required and not call.approved_approval_id:
            item.status = "blocked_approval"
            item.last_error_code = "approval_required_before_execution"
            call.status = "planned"
            call.recovery_decision = "awaiting_approval"
            self.db.commit()
            return None
        item.status = "leased"
        item.lease_owner = worker_id
        item.lease_expires_at = now + timedelta(seconds=lease_seconds)
        item.attempt_count += 1
        if call is not None:
            call.status = "leased"
            call.lease_owner = worker_id
            call.lease_expires_at = item.lease_expires_at
        self.db.commit()
        self.db.refresh(item)
        return item

    def heartbeat(self, *, queue_id: str, worker_id: str, lease_seconds: int = 60) -> AgentWorkerQueue:
        item = self.db.scalar(
            select(AgentWorkerQueue)
            .where(AgentWorkerQueue.queue_id == queue_id, AgentWorkerQueue.lease_owner == worker_id)
            .with_for_update()
        )
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent worker queue item 不存在")
        now = _utcnow()
        item.lease_expires_at = now + timedelta(seconds=lease_seconds)
        call = self.db.scalar(select(AgentToolCall).where(AgentToolCall.tool_call_id == item.tool_call_id).with_for_update())
        if call is not None:
            call.last_heartbeat_at = now
            call.lease_expires_at = item.lease_expires_at
        self.db.commit()
        self.db.refresh(item)
        return item

    def recover_orphans(self, *, now: datetime | None = None, limit: int = 100) -> int:
        current = now or _utcnow()
        items = list(self.db.scalars(
            select(AgentWorkerQueue)
            .where(
                AgentWorkerQueue.status == "leased",
                AgentWorkerQueue.lease_expires_at.is_not(None),
                AgentWorkerQueue.lease_expires_at <= current,
            )
            .order_by(AgentWorkerQueue.lease_expires_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all())
        for item in items:
            item.status = "queued"
            item.lease_owner = None
            item.lease_expires_at = None
            call = self.db.scalar(select(AgentToolCall).where(AgentToolCall.tool_call_id == item.tool_call_id).with_for_update())
            if call is not None and call.status == "leased":
                call.status = "planned"
                call.lease_owner = None
                call.lease_expires_at = None
                call.recovery_decision = "lease_expired_requeued"
        self.db.commit()
        return len(items)

    def mark_completed(self, item: AgentWorkerQueue, *, commit: bool = True) -> None:
        item.status = "completed"
        if commit:
            self.db.commit()

    def mark_failed(self, item: AgentWorkerQueue, *, error_code: str, commit: bool = True) -> None:
        item.status = "failed"
        item.last_error_code = error_code
        if commit:
            self.db.commit()


class ToolExecutor:
    def __init__(self, db: Session):
        self.db = db
        self.policy_manager = PolicyManager(db)

    def execute_next(self, *, worker_id: str) -> AgentToolCall | None:
        queue_item = AgentWorkerQueueService(self.db).claim_next(worker_id=worker_id)
        if queue_item is None:
            return None
        call = self.db.scalar(select(AgentToolCall).where(AgentToolCall.tool_call_id == queue_item.tool_call_id))
        if call is None:
            AgentWorkerQueueService(self.db).mark_failed(queue_item, error_code="tool_call_missing")
            return None
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == call.run_id))
        if run is None:
            AgentWorkerQueueService(self.db).mark_failed(queue_item, error_code="run_missing")
            return call
        user = self.db.get(User, run.user_id)
        if user is None:
            AgentWorkerQueueService(self.db).mark_failed(queue_item, error_code="user_missing")
            return call
        return self.execute_tool_call(call=call, run=run, queue_item=queue_item, current_user=user)

    def execute_tool_call(
        self,
        *,
        call: AgentToolCall,
        run: AgentRun,
        queue_item: AgentWorkerQueue | None,
        current_user: User,
    ) -> AgentToolCall:
        runtime = AgentRuntimeService(self.db)
        queue_service = AgentWorkerQueueService(self.db)
        try:
            self.policy_manager.ensure_context_allows_execution(call=call)
            self.policy_manager.ensure_approval_allows_execution(call=call)
            self.policy_manager.require_tool_execution_permissions(call=call, run=run, current_user=current_user)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_403_FORBIDDEN:
                call.status = "failed"
                call.error_code = "permission_revoked_before_execution"
                call.error_message = "Execute-time permission check failed"
                runtime.append_event(
                    run,
                    "tool.failed",
                    {"tool_call_id": call.tool_call_id, "error_code": call.error_code},
                    commit=False,
                )
                if queue_item is not None:
                    queue_service.mark_failed(queue_item, error_code=call.error_code, commit=False)
                self.db.commit()
                return call
            if exc.status_code == status.HTTP_409_CONFLICT:
                detail = exc.detail if isinstance(exc.detail, dict) else {}
                call.status = "manual_intervention"
                call.error_code = str(detail.get("code") or "approval_required_before_execution")
                call.error_message = "Approval guard blocked execution"
                runtime.append_event(
                    run,
                    "tool.failed",
                    {"tool_call_id": call.tool_call_id, "error_code": call.error_code},
                    commit=False,
                )
                if queue_item is not None:
                    queue_service.mark_failed(queue_item, error_code=call.error_code, commit=False)
                self.db.commit()
                return call
            raise

        if call.backend_effect_capability is None and call.resolved_side_effect_class not in SAFE_SIDE_EFFECT_CLASSES:
            call.status = "manual_intervention"
            call.error_code = "backend_capability_too_weak"
            runtime.append_event(run, "tool.failed", {"tool_call_id": call.tool_call_id, "error_code": call.error_code}, commit=False)
            if queue_item is not None:
                queue_service.mark_failed(queue_item, error_code=call.error_code, commit=False)
            self.db.commit()
            return call

        try:
            now = _utcnow()
            call.status = "running_pre_effect"
            call.execution_phase = "pre_effect"
            runtime.append_event(run, "tool.running", {"tool_call_id": call.tool_call_id, "tool_name": call.tool_name}, commit=False)
            call.effect_submission_state = "send_intent_recorded"
            call.downstream_send_intent_at = now
            runtime.append_event(run, "tool.send_intent_recorded", {"tool_call_id": call.tool_call_id}, commit=False)
            call.effect_submission_state = "transport_sent_observed"
            call.downstream_request_observed_sent_at = _utcnow()
            runtime.append_event(run, "tool.transport_sent_observed", {"tool_call_id": call.tool_call_id}, commit=False)

            output = AgentToolBackend(self.db).execute(
                tool_name=call.tool_name,
                payload=call.input_json_redacted,
                current_user=current_user,
            )

            if call.backend_effect_capability == "receipt_first":
                call.effect_submission_state = "backend_accepted"
                call.downstream_acceptance_id = call.idempotency_key
                call.downstream_acceptance_at = _utcnow()
                runtime.append_event(run, "tool.backend_accepted", {"tool_call_id": call.tool_call_id}, commit=False)
            call.effect_submission_state = "effect_committed"
            call.effect_boundary_crossed = call.resolved_side_effect_class not in {"read_only", "deterministic_compute"}
            call.output_json_redacted = mask_sensitive(output)
            call.output_hash = request_fingerprint(output)
            call.status = "succeeded"
            call.execution_phase = "completed"
            runtime.append_event(run, "tool.effect_committed", {"tool_call_id": call.tool_call_id}, commit=False)
            runtime.append_event(run, "tool.completed", {"tool_call_id": call.tool_call_id, "status": call.status}, commit=False)
            if queue_item is not None:
                queue_service.mark_completed(queue_item, commit=False)
            self.db.commit()
            self.db.refresh(call)
            return call
        except Exception as exc:  # noqa: BLE001
            call.status = "failed"
            call.error_code = "tool_execution_failed"
            call.error_message = str(exc)[:512]
            runtime.append_event(
                run,
                "tool.failed",
                {"tool_call_id": call.tool_call_id, "error_code": call.error_code, "error_message": call.error_message},
                commit=False,
            )
            if queue_item is not None:
                queue_service.mark_failed(queue_item, error_code=call.error_code, commit=False)
            self.db.commit()
            self.db.refresh(call)
            return call


def copy_evidence_refs(evidence_refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [mask_sensitive(dict(item)) for item in evidence_refs]


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
