from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import AgentCheckpoint, AgentMigrationBlock, AgentRun, AgentToolCall, AgentWorkerQueue
from app.models.user import User
from app.services.agent_reconcile_service import CheckpointFreshnessGate
from app.services.agent_runtime_service import AgentRuntimeService, AgentWorkerQueueService, RUN_TERMINAL_STATUSES
from app.services.permission_service import PermissionService


class AgentRunResumeService:
    def __init__(self, db: Session):
        self.db = db
        self.permission_service = PermissionService(db)

    def resume_run(self, *, run_id: str, current_user: User) -> dict[str, Any]:
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == run_id).with_for_update())
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
        self.permission_service.require_project_access(current_user, run.project_id)
        if run.status in RUN_TERMINAL_STATUSES:
            return {
                "run": run,
                "resumed": False,
                "checkpoint_freshness": {
                    "result": "terminal",
                    "action": "noop",
                    "reason": f"run_{run.status}",
                },
                "scheduled_tool_call_ids": [],
            }

        open_blocks = list(
            self.db.scalars(
                select(AgentMigrationBlock).where(
                    AgentMigrationBlock.run_id == run.run_id,
                    AgentMigrationBlock.status == "open",
                )
            ).all()
        )
        if open_blocks:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "run_migration_blocked",
                    "blocking_tool_call_ids": [item.tool_call_id for item in open_blocks if item.tool_call_id],
                },
            )

        freshness = CheckpointFreshnessGate(self.db).evaluate(run=run)
        checkpoint = self.db.get(AgentCheckpoint, run.last_checkpoint_id) if run.last_checkpoint_id else None
        if checkpoint is not None:
            checkpoint.freshness_metadata_json = freshness

        runtime = AgentRuntimeService(self.db)
        runtime.append_event(run, "checkpoint.freshness_checked", freshness, commit=False)
        if freshness["action"] != "continue_from_checkpoint":
            run.status = "paused"
            run.error_code = freshness["action"]
            run.error_message = freshness["reason"]
            runtime.append_event(
                run,
                "run.paused",
                {"reason": freshness["reason"], "action": freshness["action"]},
                commit=False,
            )
            self.db.commit()
            self.db.refresh(run)
            return {
                "run": run,
                "resumed": False,
                "checkpoint_freshness": freshness,
                "scheduled_tool_call_ids": [],
            }

        scheduled = self._schedule_retryable_tool_calls(run)
        run.status = "running"
        run.error_code = None
        run.error_message = None
        runtime.append_event(
            run,
            "run.resumed",
            {"scheduled_tool_call_ids": scheduled},
            commit=False,
        )
        self.db.commit()
        self.db.refresh(run)
        return {
            "run": run,
            "resumed": True,
            "checkpoint_freshness": freshness,
            "scheduled_tool_call_ids": scheduled,
        }

    def _schedule_retryable_tool_calls(self, run: AgentRun) -> list[str]:
        scheduled: list[str] = []
        queue = AgentWorkerQueueService(self.db)
        calls = list(
            self.db.scalars(
                select(AgentToolCall)
                .where(
                    AgentToolCall.run_id == run.run_id,
                    AgentToolCall.status == "failed_retryable",
                )
                .order_by(AgentToolCall.step_index.asc(), AgentToolCall.attempt_index.asc())
                .with_for_update()
            ).all()
        )
        for call in calls:
            existing = self.db.scalar(
                select(AgentWorkerQueue).where(
                    AgentWorkerQueue.tool_call_id == call.tool_call_id,
                    AgentWorkerQueue.status.in_(["queued", "leased"]),
                )
            )
            if existing is not None:
                continue
            call.status = "planned"
            call.recovery_decision = "resume_retry_same_idempotency_key"
            queue.enqueue_tool_call(call, commit=False)
            scheduled.append(call.tool_call_id)
        return scheduled
