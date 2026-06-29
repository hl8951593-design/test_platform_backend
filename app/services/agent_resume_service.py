from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import AgentCheckpoint, AgentMigrationBlock, AgentRun, AgentToolCall, AgentWorkerQueue
from app.models.user import User
from app.services.agent_reconcile_service import (
    CheckpointFreshnessGate,
    RUNTIME_SNAPSHOT_FRESHNESS_ACTION,
    RUNTIME_SNAPSHOT_FRESHNESS_ERROR_CODE,
)
from app.services.agent_runtime_service import AgentRuntimeService, AgentWorkerQueueService, RUN_TERMINAL_STATUSES
from app.services.agent_runtime_service import AgentConversationRunner, ToolExecutor
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

        freshness = CheckpointFreshnessGate(self.db).evaluate(run=run, current_user=current_user)
        checkpoint = self.db.get(AgentCheckpoint, run.last_checkpoint_id) if run.last_checkpoint_id else None
        if checkpoint is not None:
            checkpoint.freshness_metadata_json = freshness

        runtime = AgentRuntimeService(self.db)
        runtime.append_event(run, "checkpoint.freshness_checked", freshness, commit=False)
        if freshness["action"] != "continue_from_checkpoint":
            error_code = (
                RUNTIME_SNAPSHOT_FRESHNESS_ERROR_CODE
                if freshness["action"] == RUNTIME_SNAPSHOT_FRESHNESS_ACTION
                else freshness["action"]
            )
            run.status = "paused"
            run.error_code = error_code
            run.error_message = freshness["reason"]
            runtime.append_event(
                run,
                "run.paused",
                {"reason": freshness["reason"], "action": freshness["action"], "error_code": error_code},
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

        executed_after_approval = self._execute_approved_blocking_tool_calls(
            run=run,
            current_user=current_user,
            runtime=runtime,
        )
        scheduled = self._schedule_retryable_tool_calls(run)
        remaining_blocking = self._remaining_blocking_tool_call_ids(run)
        run.blocking_tool_call_ids_json = remaining_blocking
        run.status = "running" if not remaining_blocking else "needs_human"
        run.error_code = None
        run.error_message = None
        runtime.append_event(
            run,
            "run.resumed",
            {
                "scheduled_tool_call_ids": scheduled,
                "executed_tool_call_ids": executed_after_approval,
                "remaining_blocking_tool_call_ids": remaining_blocking,
            },
            commit=False,
        )
        self.db.commit()
        self.db.refresh(run)
        if executed_after_approval and not remaining_blocking:
            completed = AgentConversationRunner(self.db).complete_after_tool_results(
                run_id=run.run_id,
                user_id=current_user.id,
                tool_call_ids=executed_after_approval,
            )
            if completed is not None:
                run = completed
        return {
            "run": run,
            "resumed": not remaining_blocking,
            "checkpoint_freshness": freshness,
            "scheduled_tool_call_ids": scheduled,
            "executed_tool_call_ids": executed_after_approval,
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

    def _execute_approved_blocking_tool_calls(
        self,
        *,
        run: AgentRun,
        current_user: User,
        runtime: AgentRuntimeService,
    ) -> list[str]:
        blocking_ids = list(run.blocking_tool_call_ids_json or [])
        if not blocking_ids:
            return []
        executed: list[str] = []
        calls = list(
            self.db.scalars(
                select(AgentToolCall)
                .where(
                    AgentToolCall.run_id == run.run_id,
                    AgentToolCall.tool_call_id.in_(blocking_ids),
                )
                .order_by(AgentToolCall.step_index.asc(), AgentToolCall.attempt_index.asc())
                .with_for_update()
            ).all()
        )
        for call in calls:
            if call.status == "succeeded":
                executed.append(call.tool_call_id)
                continue
            if not call.approval_required or not call.approved_approval_id or call.status != "planned":
                continue
            queue_item = self.db.scalar(
                select(AgentWorkerQueue)
                .where(
                    AgentWorkerQueue.tool_call_id == call.tool_call_id,
                    AgentWorkerQueue.status.in_(["queued", "blocked_approval", "failed"]),
                )
                .order_by(AgentWorkerQueue.created_at.desc())
                .with_for_update()
                .limit(1)
            )
            refreshed = ToolExecutor(self.db).execute_tool_call(
                call=call,
                run=run,
                queue_item=queue_item,
                current_user=current_user,
            )
            self.db.refresh(run)
            if refreshed.status == "succeeded":
                run.current_iteration += 1
                run.current_step_index = max(run.current_step_index, refreshed.step_index + 1)
                runtime.append_event(
                    run,
                    "tool.result_observed",
                    {
                        "tool_call_id": refreshed.tool_call_id,
                        "tool_name": refreshed.tool_name,
                        "status": refreshed.status,
                        "resumed_after_approval": True,
                    },
                    commit=False,
                )
                executed.append(refreshed.tool_call_id)
        return executed

    def _remaining_blocking_tool_call_ids(self, run: AgentRun) -> list[str]:
        blocking_ids = list(run.blocking_tool_call_ids_json or [])
        if not blocking_ids:
            return []
        calls = {
            call.tool_call_id: call
            for call in self.db.scalars(
                select(AgentToolCall).where(
                    AgentToolCall.run_id == run.run_id,
                    AgentToolCall.tool_call_id.in_(blocking_ids),
                )
            ).all()
        }
        return [
            tool_call_id
            for tool_call_id in blocking_ids
            if calls.get(tool_call_id) is None or calls[tool_call_id].status != "succeeded"
        ]
