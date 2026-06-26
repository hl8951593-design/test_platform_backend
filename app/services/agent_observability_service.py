from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.agent import (
    AgentApproval,
    AgentContextBuild,
    AgentEvent,
    AgentLoopObservation,
    AgentMemoryContradictionEvent,
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
                item.last_error = str(exc)[:512]
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
        return summary

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


class AgentMetricsService:
    def __init__(self, db: Session):
        self.db = db

    def snapshot(self, *, project_id: int | None = None) -> dict[str, Any]:
        metrics = {
            "tool_call_uncertain_total": self._count_tool_calls(project_id, AgentToolCall.status == "uncertain"),
            "tool_call_reconcile_success_total": self._count_reconcile_attempts(project_id, "succeeded"),
            "tool_call_reconcile_manual_total": self._count_tool_calls(
                project_id, AgentToolCall.status == "manual_intervention"
            ),
            "tool_call_orphan_recovered_total": self._count_tool_calls(
                project_id, AgentToolCall.recovery_decision == "lease_expired_requeued"
            ),
            "tool_call_duplicate_blocked_total": self._count_events(project_id, "tool.duplicate_blocked"),
            "approval_superseded_total": self._count_approvals(project_id, AgentApproval.approval_status == "superseded"),
            "approval_epoch_conflict_total": self._count_events(
                project_id, "approval.approve_conflict", error_code="approval_epoch_conflict"
            ),
            "permission_revoked_before_execution_total": self._count_tool_calls(
                project_id, AgentToolCall.error_code == "permission_revoked_before_execution"
            ),
            "backend_contract_unsupported_total": self._count_tool_calls(
                project_id, AgentToolCall.error_code == "backend_contract_unsupported"
            ),
            "migration_block_open_total": self._count_migration_blocks(project_id, AgentMigrationBlock.status == "open"),
            "outbox_publish_lag_ms": AgentOutboxPublisher(self.db)._publish_lag_ms(now=_utcnow()),
            "context_degraded_total": self._count_context_builds(
                project_id, AgentContextBuild.context_degradation_level != "none"
            ),
            "context_full_evidence_required_total": self._count_context_builds(
                project_id, AgentContextBuild.required_evidence_complete.is_(False)
            ),
            "root_cause_rule_missing_total": self._count_loop_observations(
                project_id, AgentLoopObservation.root_cause_primary == "root_cause_rule_missing"
            ),
            "same_failure_no_progress_total": self._count_loop_observations(
                project_id, AgentLoopObservation.stop_action_reason == "same_failure_no_progress"
            ),
            "memory_contradiction_total": self._count_memory_contradictions(project_id),
            "memory_used_active_policy_total": self._count_memory_usage(
                project_id, AgentMemoryUsageEvent.active_for_policy.is_(True)
            ),
            "memory_high_risk_blocked_total": self._count_tool_calls(
                project_id, AgentToolCall.error_code == "memory_only_high_risk_dependency_blocked"
            ),
            "memory_needs_revalidation_total": self._count_project_memories(
                project_id, ProjectMemory.status == "needs_revalidation"
            ),
            "memory_bypassed_evidence_ref_total": self._count_events(project_id, "memory.bypassed_evidence_ref"),
            "checkpoint_freshness_failed_total": self._count_events(
                project_id, "checkpoint.freshness_checked", result="too_old"
            ),
            "backend_capability_degraded_total": self._count_tool_calls(
                project_id, AgentToolCall.backend_effect_capability.in_(["legacy_reconcile_only", "legacy_no_receipt"])
            ),
        }
        return {
            "project_id": project_id,
            "generated_at": _utcnow().isoformat(),
            "metrics": metrics,
            "derived_from": {
                "counters": "ai_agent_events and current fact tables",
                "outbox_publish_lag_ms": "oldest pending/failed ai_agent_outbox item age",
                "scope": "project" if project_id is not None else "global",
            },
        }

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

    def _count_approvals(self, project_id: int | None, *conditions: Any) -> int:
        statement = select(func.count()).select_from(AgentApproval).where(*conditions)
        if project_id is not None:
            statement = statement.where(AgentApproval.project_id == project_id)
        return int(self.db.scalar(statement) or 0)

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

    def _count_memory_contradictions(self, project_id: int | None) -> int:
        statement = select(func.count()).select_from(AgentMemoryContradictionEvent)
        if project_id is not None:
            statement = statement.where(
                AgentMemoryContradictionEvent.memory_id.in_(
                    select(ProjectMemory.id).where(ProjectMemory.project_id == project_id)
                )
            )
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


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
