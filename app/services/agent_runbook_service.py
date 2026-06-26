from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import AgentApproval, AgentEvent, AgentMigrationBlock, AgentRun, AgentToolCall
from app.models.user import User
from app.services.agent_reconcile_service import CheckpointFreshnessGate
from app.services.permission_service import PermissionService


RUNBOOKS: dict[str, dict[str, Any]] = {
    "tool_call_uncertain": {
        "title": "Runbook: uncertain ToolCall recovery",
        "trigger": "A ToolCall is uncertain or reconciling.",
        "severity": "P1",
        "steps": [
            "Inspect effect_submission_state and backend_effect_capability.",
            "Trigger run reconcile before retrying any side effect.",
            "If reconcile returns conflict or effect_committed+not_found, move to manual intervention.",
        ],
        "safe_api_actions": ["POST /api/v1/agents/runs/{run_id}/reconcile"],
    },
    "migration_blocked": {
        "title": "Runbook: migration_blocked handling",
        "trigger": "Run has open migration blocks or status=migration_blocked.",
        "severity": "P1",
        "steps": [
            "List migration blocks and inspect backend contract/schema details.",
            "Deploy or register a compatible adapter before resolving the block.",
            "Resolve the block and require checkpoint freshness gate before resume.",
        ],
        "safe_api_actions": [
            "GET /api/v1/agents/runs/{run_id}/migration-blocks",
            "POST /api/v1/agents/runs/{run_id}/migration-blocks/{block_id}/resolve",
        ],
    },
    "approval_stale": {
        "title": "Runbook: approval stale or epoch conflict",
        "trigger": "approval.approve_conflict event or pending approval with stale client data.",
        "severity": "P1",
        "steps": [
            "Refresh ToolCall detail and current approval lineage.",
            "Compare input_hash/runtime_snapshot_id/resource_scope_hash/approval_epoch.",
            "Ask the approver to review the latest pending approval; do not approve old input.",
        ],
        "safe_api_actions": [
            "GET /api/v1/agents/tool-calls/{tool_call_id}",
            "POST /api/v1/agents/tool-calls/{tool_call_id}/approve",
            "POST /api/v1/agents/tool-calls/{tool_call_id}/reject",
        ],
    },
    "checkpoint_stale": {
        "title": "Runbook: checkpoint stale handling",
        "trigger": "Checkpoint freshness gate is too_old or requires evidence rebuild.",
        "severity": "P1",
        "steps": [
            "Do not resume high-risk execution directly from a stale checkpoint.",
            "Fetch latest evidence or rebuild decision context.",
            "Resume only after freshness gate returns continue_from_checkpoint.",
        ],
        "safe_api_actions": [
            "POST /api/v1/agents/runs/{run_id}/context-builds",
            "POST /api/v1/agents/runs/{run_id}/resume",
        ],
    },
}


class AgentRunbookService:
    def __init__(self, db: Session):
        self.db = db
        self.permission_service = PermissionService(db)

    def list_runbooks(self) -> list[dict[str, Any]]:
        return [
            {"runbook_id": runbook_id, **payload}
            for runbook_id, payload in sorted(RUNBOOKS.items())
        ]

    def diagnose_run(self, *, run_id: str, current_user: User) -> dict[str, Any]:
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == run_id))
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
        self.permission_service.require_project_access(current_user, run.project_id)
        recommendations = []
        recommendations.extend(self._uncertain_recommendations(run))
        recommendations.extend(self._migration_recommendations(run))
        recommendations.extend(self._approval_recommendations(run))
        checkpoint = CheckpointFreshnessGate(self.db).evaluate(run=run)
        if checkpoint.get("result") != "fresh":
            recommendations.append({
                "runbook_id": "checkpoint_stale",
                "reason": checkpoint.get("reason"),
                "severity": RUNBOOKS["checkpoint_stale"]["severity"],
                "action": checkpoint.get("action"),
                "details": checkpoint,
            })
        return {
            "run_id": run.run_id,
            "run_status": run.status,
            "recommendations": recommendations,
            "runbooks": self.list_runbooks(),
        }

    def _uncertain_recommendations(self, run: AgentRun) -> list[dict[str, Any]]:
        calls = list(
            self.db.scalars(
                select(AgentToolCall)
                .where(
                    AgentToolCall.run_id == run.run_id,
                    AgentToolCall.status.in_(["uncertain", "reconciling"]),
                )
                .order_by(AgentToolCall.step_index.asc(), AgentToolCall.attempt_index.asc())
            ).all()
        )
        return [
            {
                "runbook_id": "tool_call_uncertain",
                "reason": "tool_call_requires_reconcile",
                "severity": RUNBOOKS["tool_call_uncertain"]["severity"],
                "action": "POST /api/v1/agents/runs/{run_id}/reconcile",
                "tool_call_id": call.tool_call_id,
                "details": {
                    "status": call.status,
                    "effect_submission_state": call.effect_submission_state,
                    "backend_effect_capability": call.backend_effect_capability,
                    "backend_operation": call.backend_operation,
                },
            }
            for call in calls
        ]

    def _migration_recommendations(self, run: AgentRun) -> list[dict[str, Any]]:
        open_blocks = list(
            self.db.scalars(
                select(AgentMigrationBlock)
                .where(AgentMigrationBlock.run_id == run.run_id, AgentMigrationBlock.status == "open")
                .order_by(AgentMigrationBlock.created_at.asc())
            ).all()
        )
        if not open_blocks and run.status != "migration_blocked":
            return []
        return [
            {
                "runbook_id": "migration_blocked",
                "reason": "open_migration_block",
                "severity": RUNBOOKS["migration_blocked"]["severity"],
                "action": "GET /api/v1/agents/runs/{run_id}/migration-blocks",
                "tool_call_id": block.tool_call_id,
                "details": {
                    "block_id": block.block_id,
                    "block_type": block.block_type,
                    "reason": block.reason,
                    "backend_name": block.backend_name,
                    "backend_operation": block.backend_operation,
                    "backend_contract_version": block.backend_contract_version,
                },
            }
            for block in open_blocks
        ] or [{
            "runbook_id": "migration_blocked",
            "reason": "run_status_migration_blocked_without_open_block",
            "severity": RUNBOOKS["migration_blocked"]["severity"],
            "action": "GET /api/v1/agents/runs/{run_id}/migration-blocks",
            "details": {"run_status": run.status},
        }]

    def _approval_recommendations(self, run: AgentRun) -> list[dict[str, Any]]:
        pending = list(
            self.db.scalars(
                select(AgentApproval)
                .where(AgentApproval.run_id == run.run_id, AgentApproval.approval_status == "pending")
                .order_by(AgentApproval.created_at.asc())
            ).all()
        )
        conflicts = list(
            self.db.scalars(
                select(AgentEvent)
                .where(AgentEvent.run_id == run.run_id, AgentEvent.event_type == "approval.approve_conflict")
                .order_by(AgentEvent.event_seq.desc())
            ).all()
        )
        recommendations: list[dict[str, Any]] = []
        for approval in pending:
            recommendations.append({
                "runbook_id": "approval_stale",
                "reason": "pending_approval_requires_fresh_review",
                "severity": RUNBOOKS["approval_stale"]["severity"],
                "action": "GET /api/v1/agents/tool-calls/{tool_call_id}",
                "tool_call_id": approval.tool_call_id,
                "details": {
                    "approval_id": approval.approval_id,
                    "approval_lineage_id": approval.approval_lineage_id,
                    "approval_epoch": approval.approval_epoch,
                    "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
                },
            })
        for event in conflicts[:3]:
            recommendations.append({
                "runbook_id": "approval_stale",
                "reason": "approval_conflict_event_seen",
                "severity": RUNBOOKS["approval_stale"]["severity"],
                "action": "GET /api/v1/agents/tool-calls/{tool_call_id}",
                "tool_call_id": (event.payload_json or {}).get("tool_call_id"),
                "details": event.payload_json,
            })
        return recommendations
