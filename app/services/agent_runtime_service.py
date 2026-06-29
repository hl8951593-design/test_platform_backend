from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.sensitive_data import mask_sensitive, request_fingerprint
from app.models.agent import (
    AgentApproval,
    AgentBackendContract,
    AgentCheckpoint,
    AgentEvent,
    AgentMemoryUsageEvent,
    AgentMigrationBlock,
    AgentOutbox,
    AgentRun,
    AgentRuntimeSnapshot,
    AgentToolCall,
    AgentWorkerQueue,
)
from app.models.user import User
from app.schemas.ai import AIChatMessage, AIChatRequest
from app.schemas.agent import AgentRunCreateRequest, AgentToolCallCreateRequest
from app.services.agent_approval_service import ApprovalService, PolicyManager
from app.services.agent_loop_service import EvidenceRefResolver, EvidenceWatchService
from app.services.agent_memory_service import MemoryCandidate, MemoryManager
from app.services.ai_service import AIService
from app.services.agent_tool_service import AgentToolBackend, SAFE_SIDE_EFFECT_CLASSES, ToolPolicyResolver, ToolRegistry
from app.services.permission_service import PermissionService


logger = logging.getLogger(__name__)

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
APPROVAL_STATUSES = ["pending", "approved", "rejected", "expired", "revoked", "superseded"]
MIGRATION_BLOCK_STATUSES = ["open", "resolved", "cancelled"]

AGENT_CONVERSATION_SYSTEM_PROMPT = (
    "你是 TestAuto 自动化测试平台的 Harness Loop Agent。"
    "你需要用简洁、可执行的中文回复用户，优先说明你能如何帮助测试平台完成接口测试、"
    "场景编排、缺陷分析、执行诊断、Agent 工具调用和运行恢复。"
    "当前能力必须以平台后端已经暴露的 Agent Run、EventStore、ToolCall、Approval、"
    "Memory、Runbook 和 Dashboard 契约为边界。"
    "当需要平台上下文或草稿能力时，只能通过下方工具协议提出一次工具调用，"
    "不要假装已经完成真实工具副作用。"
    "如果用户要求创建、生成或组合测试场景、测试用例、报告摘要等平台对象，必须优先调用可用工具，"
    "不要仅用自然语言答复。当前 Agent Run 已携带 project_id，除非工具确实缺少不可推断字段，否则不要向用户反问 project_id。"
    "当用户要求创建或组合场景组合时，必须先调用 testcase.query_project_cases 查询当前项目测试用例，"
    "再根据工具返回的真实用例 id 调用 scenario.compose_draft。"
)
AGENT_MARKDOWN_RESPONSE_PROMPT = """
面向用户的自然语言回复必须严格遵守 GitHub Flavored Markdown：
- 不要把整段回复包在 ```markdown fenced block 中。
- 标题、列表、引用、代码块和表格前后要保留合理换行。
- 如果使用表格，必须是标准 Markdown 表格：表头、分隔行和每一条数据行都必须独占一行。
- 表格分隔行只使用 `---` / `:---` / `---:` / `:---:`；不要用 `| |` 把多行表格拼在同一行。
- 表格单元格内不要直接输出未转义的 `|`；复杂说明改用列表。
- 代码必须使用闭合 fenced block，并尽量标注语言。
- 最终回复前自检 Markdown 能被前端渲染器直接渲染。
""".strip()
AGENT_TOOL_PROTOCOL_PROMPT = """
可用工具如下：
{tools}

如果需要调用工具，请只输出一个 fenced block，格式必须完全符合：
```agent_tool_request
{"tool_name":"project.read_context","input":{"project_id":123},"reason":"为什么需要这个工具","evidence_refs":[]}
```
不要在工具请求前后输出面向用户的自然语言。工具执行结果返回后，再根据结果给用户最终答复。
如果不需要工具，请直接用自然语言回答。
""".strip()
TOOL_REQUEST_BLOCK_RE = re.compile(r"```agent_tool_request\s*(?P<body>\{.*?\})\s*```", re.S)
MARKDOWN_TABLE_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")

AGENT_RUN_FIELDS = (
    "run_id",
    "project_id",
    "user_id",
    "conversation_id",
    "intent",
    "status",
    "current_iteration",
    "current_step_index",
    "max_iterations",
    "runtime_snapshot_id",
    "last_checkpoint_id",
    "last_event_sequence",
    "migration_block_count",
    "blocking_tool_call_ids_json",
    "result_json",
    "error_code",
    "error_message",
    "started_at",
    "completed_at",
    "created_at",
    "updated_at",
)

AGENT_RUN_SUMMARY_FIELDS = (
    "run",
    "assistant_message",
    "assistant_visible",
    "completion_source",
    "model_invoked",
    "model",
    "finish_reason",
    "usage",
    "event_count",
    "latest_event_sequence",
    "latest_event_types",
    "tool_call_count",
    "pending_tool_call_count",
    "approval_count",
    "pending_approval_count",
    "migration_block_count",
    "open_migration_block_count",
    "memory_usage_count",
    "blocking_tool_call_ids",
    "terminal",
    "can_cancel",
    "can_resume",
    "updated_at",
)

AGENT_RUN_ACTION_FIELDS = (
    "action_id",
    "label",
    "method",
    "path",
    "enabled",
    "reason",
    "severity",
    "resource_ids",
    "details",
)

AGENT_RUN_ACTION_STATE_FIELDS = (
    "run_summary",
    "actions",
    "primary_action_ids",
    "blocked_reasons",
    "generated_at",
)

AGENT_CONVERSATION_FIELDS = (
    "conversation_id",
    "project_id",
    "title",
    "run_count",
    "latest_run_id",
    "latest_run_status",
    "created_at",
    "updated_at",
)

AGENT_CONVERSATION_TRANSCRIPT_FIELDS = (
    "conversation",
    "turns",
    "generated_at",
)

AGENT_CONVERSATION_EXPORT_FIELDS = (
    "conversation",
    "turns",
    "events_by_run_id",
    "tool_calls_by_run_id",
    "approvals_by_run_id",
    "migration_blocks_by_run_id",
    "export_format",
    "generated_at",
    "derived_from",
)

AGENT_MODEL_HEALTH_FIELDS = (
    "provider",
    "configured",
    "base_url",
    "default_model",
    "live",
    "reachable",
    "latency_ms",
    "first_delta_received",
    "completed",
    "model",
    "finish_reason",
    "error_code",
    "error_message",
    "checked_at",
)

AGENT_CONVERSATION_SMOKE_FIELDS = (
    "project_id",
    "run_id",
    "conversation_id",
    "status",
    "completed",
    "first_delta_received",
    "assistant_visible",
    "assistant_message",
    "error_code",
    "error_message",
    "event_types",
    "latest_event_sequence",
    "run_summary",
    "latency_ms",
    "generated_at",
)

AGENT_EVENT_FIELDS = (
    "event_seq",
    "event_type",
    "payload_json",
    "created_at",
)

AGENT_RUN_EVENT_SNAPSHOT_FIELDS = (
    "run",
    "events",
    "after_sequence",
    "event_count",
    "latest_event_sequence",
    "next_after_sequence",
    "terminal",
    "generated_at",
)

RUNTIME_SNAPSHOT_FIELDS = (
    "snapshot_id",
    "project_id",
    "created_by",
    "runtime_hash",
    "tool_registry_hash",
    "manifest_bundle_hash",
    "prompt_bundle_hash",
    "policy_version_hash",
    "tools_json",
    "manifests_json",
    "adapters_json",
    "policies_json",
    "created_at",
)

TOOL_CALL_FIELDS = (
    "tool_call_id",
    "run_id",
    "step_index",
    "attempt_index",
    "runtime_snapshot_id",
    "tool_name",
    "tool_version",
    "schema_hash",
    "manifest_hash",
    "idempotency_scope",
    "idempotency_key",
    "base_side_effect_class",
    "resolved_side_effect_class",
    "base_replay_policy",
    "resolved_replay_policy",
    "policy_reason_json",
    "status",
    "execution_phase",
    "effect_submission_state",
    "input_hash",
    "input_json_redacted",
    "evidence_refs_json",
    "policy_evidence_refs_json",
    "audit_evidence_refs_json",
    "evidence_mutability_summary_json",
    "decision_context_build_id",
    "output_hash",
    "output_json_redacted",
    "required_permissions_json",
    "permission_snapshot_json",
    "approval_required",
    "approval_scope_hash",
    "approval_lineage_id",
    "approval_epoch",
    "approved_approval_id",
    "approved_by",
    "approved_at",
    "backend_name",
    "backend_operation",
    "backend_contract_version",
    "backend_request_schema_hash",
    "backend_output_schema_hash",
    "reconcile_contract_version",
    "result_adapter_version",
    "backend_effect_capability",
    "recovery_decision",
    "error_code",
    "error_message",
    "current_approval",
    "approval_lineage",
    "recent_reconcile_attempts",
    "created_at",
    "updated_at",
)


class AgentModelHealthService:
    def check(self, *, live: bool = False) -> dict[str, Any]:
        ai_service = AIService()
        provider = ai_service.provider_config()
        payload: dict[str, Any] = {
            "provider": provider.provider,
            "configured": provider.configured,
            "base_url": provider.base_url,
            "default_model": provider.default_model,
            "live": live,
            "reachable": None,
            "latency_ms": None,
            "first_delta_received": None,
            "completed": None,
            "model": None,
            "finish_reason": None,
            "error_code": None,
            "error_message": None,
            "checked_at": _utcnow(),
        }
        if not live:
            return payload
        if not provider.configured:
            payload.update(
                {
                    "reachable": False,
                    "first_delta_received": False,
                    "completed": False,
                    "error_code": "deepseek_api_key_missing",
                    "error_message": "DeepSeek API Key is not configured",
                }
            )
            return payload

        started = time.perf_counter()
        try:
            request = AIChatRequest(
                messages=[AIChatMessage(role="user", content="Please reply with exactly: ok")],
                temperature=0,
                max_tokens=32,
            )
            first_delta_received = False
            completed = False
            model = None
            finish_reason = None
            for item in ai_service.chat_stream(request):
                if item.get("type") == "delta":
                    first_delta_received = True
                elif item.get("type") == "done":
                    completed = True
                    model = item.get("model")
                    finish_reason = item.get("finish_reason")
                    break
            payload.update(
                {
                    "reachable": True,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "first_delta_received": first_delta_received,
                    "completed": completed,
                    "model": model,
                    "finish_reason": finish_reason,
                }
            )
            return payload
        except HTTPException as exc:
            payload.update(
                {
                    "reachable": False,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "first_delta_received": False,
                    "completed": False,
                    "error_code": "deepseek_http_error",
                    "error_message": _http_exception_detail(exc),
                }
            )
            return payload
        except Exception as exc:  # noqa: BLE001
            payload.update(
                {
                    "reachable": False,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "first_delta_received": False,
                    "completed": False,
                    "error_code": "deepseek_probe_error",
                    "error_message": str(exc),
                }
            )
            return payload


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
            "approval_statuses": APPROVAL_STATUSES,
            "migration_block_statuses": MIGRATION_BLOCK_STATUSES,
            "tools": self.tool_registry.registry_json(),
        }

    def run_conversation_smoke(
        self,
        *,
        project_id: int,
        intent: str,
        max_iterations: int,
        current_user: User,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        run = self.create_run(
            payload=AgentRunCreateRequest(
                project_id=project_id,
                intent=intent,
                max_iterations=max_iterations,
                auto_complete=False,
            ),
            current_user=current_user,
        )
        AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=current_user.id)
        self.db.refresh(run)
        summary = self.get_run_summary(run_id=run.run_id, current_user=current_user)
        events = list(
            self.db.scalars(
                select(AgentEvent)
                .where(AgentEvent.run_id == run.run_id)
                .order_by(AgentEvent.event_seq.asc())
            ).all()
        )
        event_types = [event.event_type for event in events]
        return {
            "project_id": project_id,
            "run_id": run.run_id,
            "conversation_id": run.conversation_id,
            "status": run.status,
            "completed": run.status == "completed",
            "first_delta_received": "model.delta" in event_types,
            "assistant_visible": bool(summary["assistant_visible"]),
            "assistant_message": summary["assistant_message"],
            "error_code": run.error_code,
            "error_message": run.error_message,
            "event_types": event_types,
            "latest_event_sequence": run.last_event_sequence,
            "run_summary": summary,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "generated_at": _utcnow(),
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
        conversation_id = payload.conversation_id or f"agent-conv-{uuid.uuid4().hex}"
        run = AgentRun(
            run_id=f"agent-run-{uuid.uuid4().hex}",
            project_id=payload.project_id,
            user_id=current_user.id,
            conversation_id=conversation_id,
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
            self.complete_run(
                run,
                {
                    "message": "Agent smoke run completed without model invocation.",
                    "completion_source": "smoke_auto_complete",
                    "model_invoked": False,
                    "assistant_visible": False,
                },
                commit=False,
            )
        self.db.commit()
        self.db.refresh(run)
        return run

    def get_run(self, *, run_id: str, current_user: User) -> AgentRun:
        run = self._get_run_or_404(run_id)
        self.permission_service.require_project_access(current_user, run.project_id)
        return run

    def get_run_summary(self, *, run_id: str, current_user: User) -> dict[str, Any]:
        run = self.get_run(run_id=run_id, current_user=current_user)
        latest_events_desc = list(
            self.db.scalars(
                select(AgentEvent)
                .where(AgentEvent.run_id == run_id)
                .order_by(AgentEvent.event_seq.desc())
                .limit(8)
            ).all()
        )
        latest_events = list(reversed(latest_events_desc))
        event_count = self._count_where(AgentEvent.run_id == run_id, model=AgentEvent)
        tool_call_count = self._count_where(AgentToolCall.run_id == run_id, model=AgentToolCall)
        pending_tool_call_count = self._count_where(
            AgentToolCall.run_id == run_id,
            AgentToolCall.status.notin_(["succeeded", "failed", "obsolete"]),
            model=AgentToolCall,
        )
        approval_count = self._count_where(AgentApproval.run_id == run_id, model=AgentApproval)
        pending_approval_count = self._count_where(
            AgentApproval.run_id == run_id,
            AgentApproval.approval_status == "pending",
            model=AgentApproval,
        )
        migration_block_count = self._count_where(AgentMigrationBlock.run_id == run_id, model=AgentMigrationBlock)
        open_migration_block_count = self._count_where(
            AgentMigrationBlock.run_id == run_id,
            AgentMigrationBlock.status == "open",
            model=AgentMigrationBlock,
        )
        memory_usage_count = self._count_where(AgentMemoryUsageEvent.run_id == run_id, model=AgentMemoryUsageEvent)

        result = run.result_json or {}
        model_completed_payload = self._latest_event_payload(run_id, "model.completed")
        assistant_visible = bool(result.get("assistant_visible", True))
        assistant_message = result.get("message") if assistant_visible else None
        model = result.get("model") or model_completed_payload.get("model")
        finish_reason = result.get("finish_reason") or model_completed_payload.get("finish_reason")
        usage = result.get("usage") or model_completed_payload.get("usage")
        model_invoked = result.get("model_invoked")
        if model_invoked is None:
            model_invoked = self._latest_event_payload(run_id, "model.started") != {}

        blocking_tool_call_ids = list(run.blocking_tool_call_ids_json or [])
        terminal = run.status in RUN_TERMINAL_STATUSES
        can_resume = (run.status in {"paused", "needs_human", "migration_blocked"} or bool(blocking_tool_call_ids)) and not terminal
        return {
            "run": run,
            "assistant_message": assistant_message,
            "assistant_visible": assistant_visible,
            "completion_source": result.get("completion_source"),
            "model_invoked": model_invoked,
            "model": model,
            "finish_reason": finish_reason,
            "usage": usage,
            "event_count": event_count,
            "latest_event_sequence": run.last_event_sequence,
            "latest_event_types": [event.event_type for event in latest_events],
            "tool_call_count": tool_call_count,
            "pending_tool_call_count": pending_tool_call_count,
            "approval_count": approval_count,
            "pending_approval_count": pending_approval_count,
            "migration_block_count": migration_block_count,
            "open_migration_block_count": open_migration_block_count,
            "memory_usage_count": memory_usage_count,
            "blocking_tool_call_ids": blocking_tool_call_ids,
            "terminal": terminal,
            "can_cancel": not terminal,
            "can_resume": can_resume,
            "updated_at": run.updated_at,
        }

    def get_run_action_state(self, *, run_id: str, current_user: User) -> dict[str, Any]:
        run_summary = self.get_run_summary(run_id=run_id, current_user=current_user)
        run = run_summary["run"]
        terminal = bool(run_summary["terminal"])
        pending_approval_ids = self._ids_where(
            AgentApproval.approval_id,
            AgentApproval.run_id == run_id,
            AgentApproval.approval_status == "pending",
            model=AgentApproval,
        )
        pending_approval_tool_call_ids = self._ids_where(
            AgentApproval.tool_call_id,
            AgentApproval.run_id == run_id,
            AgentApproval.approval_status == "pending",
            model=AgentApproval,
        )
        open_migration_block_ids = self._ids_where(
            AgentMigrationBlock.block_id,
            AgentMigrationBlock.run_id == run_id,
            AgentMigrationBlock.status == "open",
            model=AgentMigrationBlock,
        )
        uncertain_tool_call_ids = self._ids_where(
            AgentToolCall.tool_call_id,
            AgentToolCall.run_id == run_id,
            AgentToolCall.status.in_(["uncertain", "reconciling"]),
            model=AgentToolCall,
        )
        retryable_tool_call_ids = self._ids_where(
            AgentToolCall.tool_call_id,
            AgentToolCall.run_id == run_id,
            AgentToolCall.status == "failed_retryable",
            model=AgentToolCall,
        )

        blocked_reasons: list[str] = []
        if terminal:
            blocked_reasons.append(f"run_{run.status}")
        if pending_approval_ids:
            blocked_reasons.append("pending_approvals")
        if open_migration_block_ids:
            blocked_reasons.append("open_migration_blocks")
        if uncertain_tool_call_ids:
            blocked_reasons.append("uncertain_tool_calls")
        if retryable_tool_call_ids:
            blocked_reasons.append("retryable_tool_calls")
        if run.status == "paused" and run.error_code:
            blocked_reasons.append(run.error_code)

        blocking_tool_call_ids = list(dict.fromkeys(
            list(run_summary["blocking_tool_call_ids"]) + pending_approval_tool_call_ids
        ))
        resume_candidate = (
            run.status in {"paused", "needs_human"}
            or bool(blocking_tool_call_ids)
            or bool(retryable_tool_call_ids)
        )
        resume_enabled = not terminal and resume_candidate and not pending_approval_ids and not open_migration_block_ids
        if terminal:
            resume_reason = "run_terminal"
        elif open_migration_block_ids:
            resume_reason = "open_migration_blocks"
        elif pending_approval_ids:
            resume_reason = "pending_approvals_need_review"
        elif resume_candidate:
            resume_reason = "resume_candidate_ready"
        else:
            resume_reason = "no_resume_candidate"

        actions = [
            self._run_action(
                "view_summary",
                "View run summary",
                "GET",
                f"/api/v1/agents/runs/{run_id}/summary",
                True,
                "always_available",
                "info",
            ),
            self._run_action(
                "stream_events",
                "Stream events",
                "GET",
                f"/api/v1/agents/runs/{run_id}/events",
                True,
                "always_available",
                "info",
            ),
            self._run_action(
                "cancel_run",
                "Stop run",
                "POST",
                f"/api/v1/agents/runs/{run_id}/cancel",
                not terminal,
                "run_active" if not terminal else "run_terminal",
                "warning",
            ),
            self._run_action(
                "review_approvals",
                "Review approvals",
                "GET",
                f"/api/v1/agents/runs/{run_id}/approvals",
                bool(pending_approval_ids),
                "pending_approvals" if pending_approval_ids else "no_pending_approvals",
                "warning",
                pending_approval_ids,
                {"pending_approval_count": len(pending_approval_ids)},
            ),
            self._run_action(
                "resume_run",
                "Resume run",
                "POST",
                f"/api/v1/agents/runs/{run_id}/resume",
                resume_enabled,
                resume_reason,
                "primary",
                blocking_tool_call_ids + retryable_tool_call_ids,
                {
                    "blocking_tool_call_ids": blocking_tool_call_ids,
                    "pending_approval_tool_call_ids": pending_approval_tool_call_ids,
                    "retryable_tool_call_ids": retryable_tool_call_ids,
                },
            ),
            self._run_action(
                "reconcile_run",
                "Reconcile uncertain tools",
                "POST",
                f"/api/v1/agents/runs/{run_id}/reconcile",
                bool(uncertain_tool_call_ids) and not terminal,
                "uncertain_tool_calls" if uncertain_tool_call_ids else ("run_terminal" if terminal else "no_uncertain_tool_calls"),
                "warning",
                uncertain_tool_call_ids,
                {"uncertain_tool_call_count": len(uncertain_tool_call_ids)},
            ),
            self._run_action(
                "resolve_migration",
                "Resolve migration block",
                "GET",
                f"/api/v1/agents/runs/{run_id}/migration-blocks",
                bool(open_migration_block_ids),
                "open_migration_blocks" if open_migration_block_ids else "no_open_migration_blocks",
                "danger",
                open_migration_block_ids,
                {"open_migration_block_count": len(open_migration_block_ids)},
            ),
            self._run_action(
                "open_runbook",
                "Open runbook",
                "GET",
                f"/api/v1/agents/runs/{run_id}/runbook",
                bool(blocked_reasons) and run.status != "completed",
                "recovery_context_available" if blocked_reasons and run.status != "completed" else "no_recovery_context",
                "info",
                [],
                {"blocked_reasons": blocked_reasons},
            ),
        ]
        primary_action_ids = [
            action["action_id"]
            for action in actions
            if action["enabled"] and action["action_id"] in {
                "review_approvals",
                "resolve_migration",
                "reconcile_run",
                "resume_run",
                "cancel_run",
                "open_runbook",
            }
        ]
        return {
            "run_summary": run_summary,
            "actions": actions,
            "primary_action_ids": primary_action_ids,
            "blocked_reasons": blocked_reasons,
            "generated_at": _utcnow(),
        }

    def list_runs(
        self,
        *,
        project_id: int,
        current_user: User,
        conversation_id: str | None = None,
        status_filter: str | None = None,
        limit: int = 50,
    ) -> list[AgentRun]:
        self.permission_service.require_project_access(current_user, project_id)
        statement = select(AgentRun).where(AgentRun.project_id == project_id)
        if conversation_id:
            statement = statement.where(AgentRun.conversation_id == conversation_id)
        if status_filter:
            statement = statement.where(AgentRun.status == status_filter)
        return list(
            self.db.scalars(
                statement.order_by(AgentRun.updated_at.desc(), AgentRun.id.desc()).limit(limit)
            ).all()
        )

    def _count_where(self, *criteria, model) -> int:
        return int(
            self.db.scalar(
                select(func.count()).select_from(model).where(*criteria)
            )
            or 0
        )

    def _latest_event_payload(self, run_id: str, event_type: str) -> dict[str, Any]:
        event = self.db.scalar(
            select(AgentEvent)
            .where(AgentEvent.run_id == run_id, AgentEvent.event_type == event_type)
            .order_by(AgentEvent.event_seq.desc())
            .limit(1)
        )
        if event is None:
            return {}
        return dict(event.payload_json or {})

    def _ids_where(self, column, *criteria, model) -> list[str]:
        return [
            str(value)
            for value in self.db.scalars(
                select(column).select_from(model).where(*criteria)
            ).all()
        ]

    @staticmethod
    def _run_action(
        action_id: str,
        label: str,
        method: str,
        path: str,
        enabled: bool,
        reason: str,
        severity: str,
        resource_ids: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "action_id": action_id,
            "label": label,
            "method": method,
            "path": path,
            "enabled": enabled,
            "reason": reason,
            "severity": severity,
            "resource_ids": resource_ids or [],
            "details": details or {},
        }

    def list_conversations(
        self,
        *,
        project_id: int,
        current_user: User,
        search: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        self.permission_service.require_project_access(current_user, project_id)
        runs = list(
            self.db.scalars(
                select(AgentRun)
                .where(AgentRun.project_id == project_id, AgentRun.conversation_id.is_not(None))
                .order_by(AgentRun.updated_at.desc(), AgentRun.id.desc())
            ).all()
        )
        conversations: dict[str, dict[str, Any]] = {}
        for run in runs:
            if run.conversation_id is None:
                continue
            title = _conversation_title(run.intent)
            if search and search.lower() not in title.lower() and search.lower() not in run.conversation_id.lower():
                continue
            existing = conversations.get(run.conversation_id)
            if existing is None:
                conversations[run.conversation_id] = {
                    "conversation_id": run.conversation_id,
                    "project_id": run.project_id,
                    "title": title,
                    "run_count": 1,
                    "latest_run_id": run.run_id,
                    "latest_run_status": run.status,
                    "created_at": run.created_at,
                    "updated_at": run.updated_at,
                }
            else:
                existing["run_count"] += 1
                if run.created_at < existing["created_at"]:
                    existing["created_at"] = run.created_at
                    existing["title"] = title
        return sorted(conversations.values(), key=lambda item: item["updated_at"], reverse=True)[:limit]

    def get_conversation_transcript(
        self,
        *,
        project_id: int,
        conversation_id: str,
        current_user: User,
        limit: int = 100,
    ) -> dict[str, Any]:
        self.permission_service.require_project_access(current_user, project_id)
        statement = (
            select(AgentRun)
            .where(
                AgentRun.project_id == project_id,
                AgentRun.conversation_id == conversation_id,
            )
            .order_by(AgentRun.created_at.asc(), AgentRun.id.asc())
            .limit(limit)
        )
        runs = list(self.db.scalars(statement).all())
        if not runs:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent conversation 不存在")

        run_count = self._count_where(
            AgentRun.project_id == project_id,
            AgentRun.conversation_id == conversation_id,
            model=AgentRun,
        )
        latest_run = self.db.scalar(
            select(AgentRun)
            .where(
                AgentRun.project_id == project_id,
                AgentRun.conversation_id == conversation_id,
            )
            .order_by(AgentRun.updated_at.desc(), AgentRun.id.desc())
            .limit(1)
        )
        first_run = runs[0]
        latest = latest_run or runs[-1]
        conversation = {
            "conversation_id": conversation_id,
            "project_id": project_id,
            "title": _conversation_title(first_run.intent),
            "run_count": run_count,
            "latest_run_id": latest.run_id,
            "latest_run_status": latest.status,
            "created_at": first_run.created_at,
            "updated_at": latest.updated_at,
        }
        return {
            "conversation": conversation,
            "turns": [
                self.get_run_summary(run_id=run.run_id, current_user=current_user)
                for run in runs
            ],
            "generated_at": _utcnow(),
        }

    def export_conversation(
        self,
        *,
        project_id: int,
        conversation_id: str,
        current_user: User,
        limit: int = 100,
    ) -> dict[str, Any]:
        transcript = self.get_conversation_transcript(
            project_id=project_id,
            conversation_id=conversation_id,
            current_user=current_user,
            limit=limit,
        )
        run_ids = [turn["run"].run_id for turn in transcript["turns"]]
        events_by_run_id: dict[str, list[AgentEvent]] = {run_id: [] for run_id in run_ids}
        tool_calls_by_run_id: dict[str, list[AgentToolCall]] = {run_id: [] for run_id in run_ids}
        approvals_by_run_id: dict[str, list[AgentApproval]] = {run_id: [] for run_id in run_ids}
        migration_blocks_by_run_id: dict[str, list[AgentMigrationBlock]] = {run_id: [] for run_id in run_ids}

        if run_ids:
            for event in self.db.scalars(
                select(AgentEvent)
                .where(AgentEvent.run_id.in_(run_ids))
                .order_by(AgentEvent.run_id.asc(), AgentEvent.event_seq.asc())
            ).all():
                events_by_run_id.setdefault(event.run_id, []).append(event)
            for tool_call in self.db.scalars(
                select(AgentToolCall)
                .where(AgentToolCall.run_id.in_(run_ids))
                .order_by(AgentToolCall.run_id.asc(), AgentToolCall.step_index.asc(), AgentToolCall.attempt_index.asc(), AgentToolCall.id.asc())
            ).all():
                tool_calls_by_run_id.setdefault(tool_call.run_id, []).append(tool_call)
            for approval in self.db.scalars(
                select(AgentApproval)
                .where(AgentApproval.run_id.in_(run_ids))
                .order_by(AgentApproval.run_id.asc(), AgentApproval.created_at.asc(), AgentApproval.id.asc())
            ).all():
                approvals_by_run_id.setdefault(approval.run_id, []).append(approval)
            for block in self.db.scalars(
                select(AgentMigrationBlock)
                .where(AgentMigrationBlock.run_id.in_(run_ids))
                .order_by(AgentMigrationBlock.run_id.asc(), AgentMigrationBlock.created_at.asc(), AgentMigrationBlock.id.asc())
            ).all():
                migration_blocks_by_run_id.setdefault(block.run_id, []).append(block)

        return {
            **transcript,
            "events_by_run_id": events_by_run_id,
            "tool_calls_by_run_id": tool_calls_by_run_id,
            "approvals_by_run_id": approvals_by_run_id,
            "migration_blocks_by_run_id": migration_blocks_by_run_id,
            "export_format": "agent_conversation_export_v1",
            "generated_at": _utcnow(),
            "derived_from": {
                "conversation": "ai_agent_runs",
                "turns": "AgentRunSummaryRead",
                "events": "ai_agent_events",
                "tool_calls": "ai_agent_tool_calls",
                "approvals": "ai_agent_approvals",
                "migration_blocks": "ai_agent_migration_blocks",
                "run_ids": run_ids,
                "limit": limit,
            },
        }

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

    def get_event_snapshot(
        self,
        *,
        run_id: str,
        after_sequence: int,
        limit: int,
        current_user: User,
    ) -> dict[str, Any]:
        run = self.get_run(run_id=run_id, current_user=current_user)
        events = list(self.db.scalars(
            select(AgentEvent)
            .where(AgentEvent.run_id == run_id, AgentEvent.event_seq > after_sequence)
            .order_by(AgentEvent.event_seq)
            .limit(limit)
        ).all())
        next_after_sequence = events[-1].event_seq if events else after_sequence
        return {
            "run": run,
            "events": events,
            "after_sequence": after_sequence,
            "event_count": len(events),
            "latest_event_sequence": run.last_event_sequence,
            "next_after_sequence": next_after_sequence,
            "terminal": run.status in RUN_TERMINAL_STATUSES,
            "generated_at": _utcnow(),
        }

    def append_event(
        self,
        run: AgentRun,
        event_type: str,
        payload: dict[str, Any],
        *,
        commit: bool = True,
    ) -> AgentEvent:
        try:
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
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": "event_outbox_write_failed"},
            ) from exc

    def complete_run(self, run: AgentRun, result: dict[str, Any], *, commit: bool = True) -> AgentRun:
        run.status = "completed"
        run.result_json = mask_sensitive(result)
        run.completed_at = _utcnow()
        self.append_event(run, "run.completed", {"result": run.result_json}, commit=False)
        if commit:
            self.db.commit()
            self.db.refresh(run)
        return run

    def fail_run(self, run: AgentRun, *, error_code: str, error_message: str, commit: bool = True) -> AgentRun:
        run.status = "failed"
        run.error_code = error_code
        run.error_message = error_message[:512]
        run.completed_at = _utcnow()
        self.append_event(
            run,
            "run.failed",
            {"error_code": run.error_code, "error_message": run.error_message},
            commit=False,
        )
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


class AgentConversationRunner:
    def __init__(self, db: Session):
        self.db = db

    def complete_after_tool_results(
        self,
        *,
        run_id: str,
        user_id: int,
        tool_call_ids: list[str],
    ) -> AgentRun | None:
        runtime = AgentRuntimeService(self.db)
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == run_id))
        user = self.db.get(User, user_id)
        if run is None or user is None:
            return None
        if run.status in RUN_TERMINAL_STATUSES:
            return run

        calls = list(
            self.db.scalars(
                select(AgentToolCall)
                .where(
                    AgentToolCall.run_id == run.run_id,
                    AgentToolCall.tool_call_id.in_(tool_call_ids),
                )
                .order_by(AgentToolCall.step_index.asc(), AgentToolCall.attempt_index.asc())
            ).all()
        )
        messages = self._build_chat_messages(run, current_user=user, runtime=runtime)
        for call in calls:
            messages.append(AIChatMessage(role="user", content=_tool_result_message(call)))
        messages.append(AIChatMessage(
            role="user",
            content="以上工具已完成审批和执行。请基于这些工具结果给用户最终回复，不要再请求工具。",
        ))

        try:
            content, chunks, model_payload = self._stream_model_response(
                run=run,
                messages=messages,
                runtime=runtime,
                iteration=run.current_iteration,
                final_summary=True,
            )
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES:
                return run
            clean_model_payload = {key: value for key, value in model_payload.items() if value is not None}
            content, chunks = self._normalize_user_visible_markdown(
                run=run,
                runtime=runtime,
                content=content,
                chunks=chunks,
                iteration=run.current_iteration,
                final_summary=True,
            )
            self._emit_model_deltas(run=run, runtime=runtime, chunks=chunks)
            runtime.append_event(
                run,
                "model.completed",
                {
                    "content": content,
                    "iteration": run.current_iteration,
                    "final_summary": True,
                    "resumed_after_approval": True,
                    **clean_model_payload,
                },
                commit=False,
            )
            return runtime.complete_run(
                run,
                {
                    "message": content,
                    "tool_calls": [_tool_call_summary(call) for call in calls],
                    **clean_model_payload,
                },
                commit=True,
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            return runtime.fail_run(
                run,
                error_code="agent_conversation_model_error",
                error_message=detail,
                commit=True,
            )
        except Exception as exc:  # noqa: BLE001
            return runtime.fail_run(
                run,
                error_code="agent_conversation_unhandled_error",
                error_message=str(exc),
                commit=True,
            )

    def run(self, *, run_id: str, user_id: int) -> AgentRun | None:
        runtime = AgentRuntimeService(self.db)
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == run_id))
        user = self.db.get(User, user_id)
        if run is None or user is None:
            logger.warning("agent_conversation_skip_missing run_id=%s user_id=%s", run_id, user_id)
            return None
        if run.status in RUN_TERMINAL_STATUSES:
            logger.info("agent_conversation_skip_terminal run_id=%s status=%s", run.run_id, run.status)
            return run

        try:
            logger.info(
                "agent_conversation_start run_id=%s project_id=%s user_id=%s conversation_id=%s max_iterations=%s",
                run.run_id,
                run.project_id,
                user.id,
                run.conversation_id,
                run.max_iterations,
            )
            messages = self._build_chat_messages(run, current_user=user, runtime=runtime)
            tool_summaries: list[dict[str, Any]] = []
            for iteration in range(max(1, run.max_iterations)):
                content, chunks, model_payload = self._stream_model_response(
                    run=run,
                    messages=messages,
                    runtime=runtime,
                    iteration=iteration,
                )
                self.db.refresh(run)
                if run.status in RUN_TERMINAL_STATUSES:
                    return run
                clean_model_payload = {key: value for key, value in model_payload.items() if value is not None}
                try:
                    tool_request = self._parse_tool_request(content)
                except HTTPException as exc:
                    content, chunks, clean_model_payload, tool_request = self._repair_invalid_tool_request(
                        run=run,
                        messages=messages,
                        invalid_content=content,
                        error_message=_http_exception_detail(exc),
                        runtime=runtime,
                        iteration=iteration,
                    )
                    self.db.refresh(run)
                    if run.status in RUN_TERMINAL_STATUSES:
                        return run
                if tool_request is None:
                    content, chunks = self._normalize_user_visible_markdown(
                        run=run,
                        runtime=runtime,
                        content=content,
                        chunks=chunks,
                        iteration=iteration,
                        final_summary=False,
                    )
                    self._emit_model_deltas(run=run, runtime=runtime, chunks=chunks)
                    runtime.append_event(
                        run,
                        "model.completed",
                        {
                            "content": content,
                            "iteration": iteration,
                            "requested_tool": False,
                            **clean_model_payload,
                        },
                        commit=False,
                    )
                    result = {"message": content, **clean_model_payload}
                    if tool_summaries:
                        result["tool_calls"] = tool_summaries
                    logger.info(
                        "agent_conversation_complete_without_tool run_id=%s iteration=%s content_length=%s",
                        run.run_id,
                        iteration,
                        len(content),
                    )
                    return runtime.complete_run(run, result, commit=True)

                runtime.append_event(
                    run,
                    "model.completed",
                    {
                        "content": content,
                        "iteration": iteration,
                        "requested_tool": True,
                        **clean_model_payload,
                    },
                    commit=False,
                )
                runtime.append_event(
                    run,
                    "model.tool_request_detected",
                    {
                        "iteration": iteration,
                        "tool_name": tool_request["tool_name"],
                        "reason": tool_request.get("reason"),
                    },
                    commit=True,
                )
                logger.info(
                    "agent_tool_request_detected run_id=%s iteration=%s tool_name=%s reason=%s",
                    run.run_id,
                    iteration,
                    tool_request["tool_name"],
                    tool_request.get("reason"),
                )
                self.db.refresh(run)
                if run.status in RUN_TERMINAL_STATUSES:
                    return run
                messages.append(AIChatMessage(role="assistant", content=content))
                call = self._create_and_execute_tool_request(
                    run=run,
                    current_user=user,
                    tool_request=tool_request,
                    iteration=iteration,
                )
                logger.info(
                    "agent_tool_request_finished run_id=%s iteration=%s tool_call_id=%s tool_name=%s status=%s",
                    run.run_id,
                    iteration,
                    call.tool_call_id,
                    call.tool_name,
                    call.status,
                )
                tool_summaries.append(_tool_call_summary(call))
                self.db.refresh(run)
                if run.status == "needs_human":
                    return run
                messages.append(AIChatMessage(role="user", content=_tool_result_message(call)))

            content, chunks, model_payload = self._stream_model_response(
                run=run,
                messages=[
                    *messages,
                    AIChatMessage(
                        role="user",
                        content="工具迭代次数已达到上限。请基于当前已返回的工具结果给出最终总结，不要再请求工具。",
                    ),
                ],
                runtime=runtime,
                iteration=run.max_iterations,
                final_summary=True,
            )
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES:
                return run
            clean_model_payload = {key: value for key, value in model_payload.items() if value is not None}
            content, chunks = self._normalize_user_visible_markdown(
                run=run,
                runtime=runtime,
                content=content,
                chunks=chunks,
                iteration=run.max_iterations,
                final_summary=True,
            )
            self._emit_model_deltas(run=run, runtime=runtime, chunks=chunks)
            runtime.append_event(
                run,
                "model.completed",
                {"content": content, "iteration": run.max_iterations, "final_summary": True, **clean_model_payload},
                commit=False,
            )
            logger.info(
                "agent_conversation_complete_after_tools run_id=%s tool_call_count=%s content_length=%s",
                run.run_id,
                len(tool_summaries),
                len(content),
            )
            return runtime.complete_run(run, {"message": content, "tool_calls": tool_summaries, **clean_model_payload}, commit=True)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            logger.warning(
                "agent_conversation_failed_http run_id=%s project_id=%s error=%s",
                run.run_id,
                run.project_id,
                detail,
            )
            return runtime.fail_run(
                run,
                error_code="agent_conversation_model_error",
                error_message=detail,
                commit=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("agent_conversation_failed_unhandled run_id=%s project_id=%s", run.run_id, run.project_id)
            return runtime.fail_run(
                run,
                error_code="agent_conversation_unhandled_error",
                error_message=str(exc),
                commit=True,
            )

    def _stream_model_response(
        self,
        *,
        run: AgentRun,
        messages: list[AIChatMessage],
        runtime: AgentRuntimeService,
        iteration: int,
        final_summary: bool = False,
        repair_attempt: bool = False,
    ) -> tuple[str, list[str], dict[str, Any]]:
        content_parts: list[str] = []
        model_payload: dict[str, Any] = {}
        runtime.append_event(
            run,
            "model.started",
            {
                "provider": AIService.provider,
                "iteration": iteration,
                "final_summary": final_summary,
                "repair_attempt": repair_attempt,
            },
            commit=True,
        )
        logger.info(
            "agent_model_stream_start run_id=%s project_id=%s iteration=%s final_summary=%s repair_attempt=%s message_count=%s",
            run.run_id,
            run.project_id,
            iteration,
            final_summary,
            repair_attempt,
            len(messages),
        )
        request = AIChatRequest(messages=messages, temperature=0.2)
        deltas_emitted = False
        first_delta_logged = False
        for item in AIService().chat_stream(request):
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES:
                break
            if item.get("type") == "delta":
                delta = str(item.get("content") or "")
                if delta:
                    content_parts.append(delta)
                    content = "".join(content_parts)
                    if deltas_emitted:
                        if not first_delta_logged:
                            logger.info(
                                "agent_model_first_delta run_id=%s iteration=%s final_summary=%s",
                                run.run_id,
                                iteration,
                                final_summary,
                            )
                            first_delta_logged = True
                        runtime.append_event(run, "model.delta", {"content": delta}, commit=True)
                    elif not _should_hold_for_tool_request_detection(content):
                        deltas_emitted = True
                        if not first_delta_logged:
                            logger.info(
                                "agent_model_first_delta run_id=%s iteration=%s final_summary=%s",
                                run.run_id,
                                iteration,
                                final_summary,
                            )
                            first_delta_logged = True
                        for pending_delta in content_parts:
                            runtime.append_event(run, "model.delta", {"content": pending_delta}, commit=True)
            elif item.get("type") == "done":
                model_payload = {
                    "provider": AIService.provider,
                    "model": item.get("model"),
                    "finish_reason": item.get("finish_reason"),
                    "usage": item.get("usage"),
                }
        content = "".join(content_parts).strip()
        if content_parts and not deltas_emitted and not _looks_like_tool_request_content(content):
            if not first_delta_logged:
                logger.info(
                    "agent_model_first_delta run_id=%s iteration=%s final_summary=%s",
                    run.run_id,
                    iteration,
                    final_summary,
                )
                first_delta_logged = True
            for pending_delta in content_parts:
                runtime.append_event(run, "model.delta", {"content": pending_delta}, commit=True)
            deltas_emitted = True
        logger.info(
            "agent_model_stream_done run_id=%s iteration=%s final_summary=%s content_length=%s deltas_emitted=%s finish_reason=%s model=%s",
            run.run_id,
            iteration,
            final_summary,
            len(content),
            deltas_emitted,
            model_payload.get("finish_reason"),
            model_payload.get("model"),
        )
        return content, [] if deltas_emitted else content_parts, model_payload

    def _emit_model_deltas(
        self,
        *,
        run: AgentRun,
        runtime: AgentRuntimeService,
        chunks: list[str],
    ) -> None:
        for delta in chunks:
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES:
                return
            runtime.append_event(run, "model.delta", {"content": delta}, commit=True)

    def _normalize_user_visible_markdown(
        self,
        *,
        run: AgentRun,
        runtime: AgentRuntimeService,
        content: str,
        chunks: list[str],
        iteration: int,
        final_summary: bool,
    ) -> tuple[str, list[str]]:
        normalized = _normalize_agent_markdown_response(content)
        if normalized == content:
            return content, chunks
        logger.info(
            "agent_markdown_response_normalized run_id=%s iteration=%s final_summary=%s original_length=%s normalized_length=%s",
            run.run_id,
            iteration,
            final_summary,
            len(content),
            len(normalized),
        )
        runtime.append_event(
            run,
            "model.markdown_normalized",
            {
                "iteration": iteration,
                "final_summary": final_summary,
                "original_length": len(content),
                "normalized_length": len(normalized),
                "content": normalized,
                "replace_content": True,
            },
            commit=False,
        )
        return normalized, [normalized] if chunks else chunks

    def _parse_tool_request(self, content: str) -> dict[str, Any] | None:
        raw = None
        match = TOOL_REQUEST_BLOCK_RE.search(content)
        if match:
            raw = match.group("body")
        else:
            stripped = content.strip()
            if stripped.startswith("{") and stripped.endswith("}") and '"tool_name"' in stripped:
                raw = stripped
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="模型工具请求不是合法 JSON",
            ) from exc
        tool_name = payload.get("tool_name")
        if not isinstance(tool_name, str) or not tool_name:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="模型工具请求缺少 tool_name")
        tool_input = payload.get("input", {})
        if tool_input is None:
            tool_input = {}
        if not isinstance(tool_input, dict):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="模型工具 input 必须是对象")
        evidence_refs = payload.get("evidence_refs", [])
        if evidence_refs is None:
            evidence_refs = []
        if not isinstance(evidence_refs, list) or not all(isinstance(item, dict) for item in evidence_refs):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="模型工具 evidence_refs 必须是对象列表")
        return {
            "tool_name": tool_name,
            "input": tool_input,
            "reason": payload.get("reason") if isinstance(payload.get("reason"), str) else None,
            "evidence_refs": evidence_refs,
        }

    def _repair_invalid_tool_request(
        self,
        *,
        run: AgentRun,
        messages: list[AIChatMessage],
        invalid_content: str,
        error_message: str,
        runtime: AgentRuntimeService,
        iteration: int,
    ) -> tuple[str, list[str], dict[str, Any], dict[str, Any] | None]:
        runtime.append_event(
            run,
            "model.tool_request_invalid",
            {
                "iteration": iteration,
                "error_message": error_message,
                "content_preview": invalid_content[:500],
            },
            commit=True,
        )
        repair_messages = [
            *messages,
            AIChatMessage(role="assistant", content=invalid_content),
            AIChatMessage(
                role="user",
                content=(
                    "上一条回复看起来想调用工具，但 agent_tool_request 格式无效。"
                    f"错误：{error_message}\n"
                    "请重新输出：如果仍需工具，请只输出一个合法的 ```agent_tool_request fenced JSON block；"
                    "如果不需要工具，请直接给用户自然语言回复。不要解释格式错误。"
                ),
            ),
        ]
        repaired_content, repaired_chunks, repaired_payload = self._stream_model_response(
            run=run,
            messages=repair_messages,
            runtime=runtime,
            iteration=iteration,
            repair_attempt=True,
        )
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            return repaired_content, repaired_chunks, repaired_payload, None
        clean_payload = {key: value for key, value in repaired_payload.items() if value is not None}
        try:
            tool_request = self._parse_tool_request(repaired_content)
        except HTTPException as exc:
            runtime.append_event(
                run,
                "model.tool_request_repair_failed",
                {
                    "iteration": iteration,
                    "error_message": _http_exception_detail(exc),
                    "content_preview": repaired_content[:500],
                },
                commit=True,
            )
            raise
        runtime.append_event(
            run,
            "model.tool_request_repaired",
            {
                "iteration": iteration,
                "requested_tool": tool_request is not None,
                "tool_name": tool_request["tool_name"] if tool_request else None,
            },
            commit=True,
        )
        return repaired_content, repaired_chunks, clean_payload, tool_request

    def _create_and_execute_tool_request(
        self,
        *,
        run: AgentRun,
        current_user: User,
        tool_request: dict[str, Any],
        iteration: int,
    ) -> AgentToolCall:
        runtime = AgentRuntimeService(self.db)
        tool_input = self._normalize_tool_input(
            run=run,
            tool_name=tool_request["tool_name"],
            tool_input=dict(tool_request["input"]),
        )
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name=tool_request["tool_name"],
                input=tool_input,
                step_index=run.current_step_index,
                attempt_index=iteration,
                evidence_refs=tool_request["evidence_refs"],
            ),
            current_user=current_user,
            enqueue=False,
        )
        self.db.refresh(run)
        if call.approval_required:
            blocking = list(run.blocking_tool_call_ids_json or [])
            if call.tool_call_id not in blocking:
                blocking.append(call.tool_call_id)
            run.status = "needs_human"
            run.blocking_tool_call_ids_json = blocking
            runtime.append_event(
                run,
                "run.needs_human",
                {
                    "reason": "tool_approval_required",
                    "tool_call_id": call.tool_call_id,
                    "tool_name": call.tool_name,
                },
                commit=False,
            )
            self.db.commit()
            self.db.refresh(run)
            self.db.refresh(call)
            return call

        if self._should_block_tool_request_before_execution(run=run, call=call):
            output = {
                "required_tool": "testcase.query_project_cases",
                "blocked_tool": call.tool_name,
                "next_action": (
                    "Call testcase.query_project_cases for the current project, then use the returned "
                    "test case ids when calling scenario.compose_draft."
                ),
            }
            call.status = "failed"
            call.execution_phase = "blocked_by_harness"
            call.error_code = "scenario_compose_requires_case_query"
            call.error_message = (
                "scenario.compose_draft requires a successful testcase.query_project_cases result "
                "in the same Agent Run before execution."
            )
            call.output_json_redacted = output
            call.output_hash = request_fingerprint(output)
            run.current_iteration = iteration + 1
            run.current_step_index += 1
            runtime.append_event(
                run,
                "tool.failed",
                {
                    "tool_call_id": call.tool_call_id,
                    "tool_name": call.tool_name,
                    "error_code": call.error_code,
                    "error_message": call.error_message,
                },
                commit=False,
            )
            runtime.append_event(
                run,
                "tool.result_observed",
                {
                    "tool_call_id": call.tool_call_id,
                    "tool_name": call.tool_name,
                    "status": call.status,
                    "error_code": call.error_code,
                },
                commit=False,
            )
            self.db.commit()
            self.db.refresh(run)
            self.db.refresh(call)
            return call

        executed = ToolExecutor(self.db).execute_tool_call(
            call=call,
            run=run,
            queue_item=None,
            current_user=current_user,
        )
        self.db.refresh(run)
        run.current_iteration = iteration + 1
        run.current_step_index += 1
        runtime.append_event(
            run,
            "tool.result_observed",
            {
                "tool_call_id": executed.tool_call_id,
                "tool_name": executed.tool_name,
                "status": executed.status,
            },
            commit=False,
        )
        self.db.commit()
        self.db.refresh(run)
        self.db.refresh(executed)
        return executed

    def _normalize_tool_input(self, *, run: AgentRun, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        spec = ToolRegistry().get(tool_name)
        required = set((spec.input_schema or {}).get("required") or [])
        if "project_id" in required and "project_id" not in tool_input:
            tool_input["project_id"] = run.project_id
        return tool_input

    def _should_block_tool_request_before_execution(self, *, run: AgentRun, call: AgentToolCall) -> bool:
        if call.tool_name != "scenario.compose_draft":
            return False
        return not self._has_successful_project_case_query(run)

    def _has_successful_project_case_query(self, run: AgentRun) -> bool:
        return self.db.scalar(
            select(AgentToolCall.tool_call_id)
            .where(
                AgentToolCall.run_id == run.run_id,
                AgentToolCall.tool_name == "testcase.query_project_cases",
                AgentToolCall.status == "succeeded",
            )
            .limit(1)
        ) is not None

    def _build_chat_messages(
        self,
        run: AgentRun,
        *,
        current_user: User,
        runtime: AgentRuntimeService,
    ) -> list[AIChatMessage]:
        messages = [AIChatMessage(role="system", content=_conversation_system_prompt())]
        messages.append(AIChatMessage(role="system", content=_format_run_context(run)))
        memory_context = self._memory_context_message(run=run, current_user=current_user, runtime=runtime)
        if memory_context is not None:
            messages.append(memory_context)
        if run.conversation_id:
            previous_runs = list(
                self.db.scalars(
                    select(AgentRun)
                    .where(
                        AgentRun.project_id == run.project_id,
                        AgentRun.conversation_id == run.conversation_id,
                        AgentRun.id < run.id,
                    )
                    .order_by(AgentRun.id.desc())
                    .limit(8)
                ).all()
            )
            for previous in reversed(previous_runs):
                messages.append(AIChatMessage(role="user", content=previous.intent))
                assistant_content = _assistant_message_from_run(previous)
                if assistant_content:
                    messages.append(AIChatMessage(role="assistant", content=assistant_content))
        messages.append(AIChatMessage(role="user", content=run.intent))
        return messages

    def _memory_context_message(
        self,
        *,
        run: AgentRun,
        current_user: User,
        runtime: AgentRuntimeService,
    ) -> AIChatMessage | None:
        try:
            candidates = MemoryManager(self.db).retrieve(
                project_id=run.project_id,
                query=run.intent,
                profile_name="normal_plan_v1",
                task_risk="normal",
                usage_role="conversation_context",
                current_user=current_user,
                run_id=run.run_id,
                step_index=run.current_step_index,
                limit=5,
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
            runtime.append_event(
                run,
                "memory.context_unavailable",
                {
                    "profile_name": "normal_plan_v1",
                    "usage_role": "conversation_context",
                    "error": detail,
                },
                commit=True,
            )
            return None
        if not candidates:
            return None
        runtime.append_event(
            run,
            "memory.context_injected",
            {
                "profile_name": "normal_plan_v1",
                "usage_role": "conversation_context",
                "active_for_policy": False,
                "memory_ids": [candidate.memory_id for candidate in candidates],
                "memory_versions": {
                    str(candidate.memory_id): candidate.memory_version
                    for candidate in candidates
                },
                "count": len(candidates),
            },
            commit=True,
        )
        return AIChatMessage(role="system", content=_format_memory_context(candidates))


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
        if call is not None and call.status in {"uncertain", "reconciling"}:
            item.status = "failed"
            item.last_error_code = "tool_call_uncertain_reconcile_required"
            call.error_code = "tool_call_uncertain_reconcile_required"
            call.recovery_decision = "reconcile_required_before_execution"
            call_run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == call.run_id))
            if call_run is not None:
                AgentRuntimeService(self.db).append_event(
                    call_run,
                    "tool.failed",
                    {"tool_call_id": call.tool_call_id, "error_code": call.error_code},
                    commit=False,
                )
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
    def __init__(
        self,
        db: Session,
        *,
        runtime_factory: Callable[[Session], AgentRuntimeService] = AgentRuntimeService,
        backend_factory: Callable[[Session], AgentToolBackend] = AgentToolBackend,
    ):
        self.db = db
        self.policy_manager = PolicyManager(db)
        self.runtime_factory = runtime_factory
        self.backend_factory = backend_factory

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
        runtime = self.runtime_factory(self.db)
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

            output = self.backend_factory(self.db).execute(
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
            try:
                runtime.append_event(run, "tool.effect_committed", {"tool_call_id": call.tool_call_id}, commit=False)
                runtime.append_event(run, "tool.completed", {"tool_call_id": call.tool_call_id, "status": call.status}, commit=False)
            except Exception as exc:  # noqa: BLE001
                return self._mark_eventstore_write_failed_after_effect(call=call, queue_item=queue_item, queue_service=queue_service, exc=exc)
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

    def _mark_eventstore_write_failed_after_effect(
        self,
        *,
        call: AgentToolCall,
        queue_item: AgentWorkerQueue | None,
        queue_service: AgentWorkerQueueService,
        exc: Exception,
    ) -> AgentToolCall:
        call.status = "uncertain"
        call.execution_phase = "completed"
        call.error_code = "eventstore_write_failed_after_effect"
        call.error_message = str(exc)[:512]
        call.recovery_decision = "reconcile_required_after_eventstore_failure"
        if queue_item is not None:
            queue_service.mark_failed(queue_item, error_code=call.error_code, commit=False)
        self.db.commit()
        self.db.refresh(call)
        return call


def copy_evidence_refs(evidence_refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [mask_sensitive(dict(item)) for item in evidence_refs]


def _conversation_system_prompt() -> str:
    tools = [
        {
            "name": spec.name,
            "summary": spec.summary,
            "input_schema": spec.input_schema,
            "side_effect_class": spec.side_effect_class,
            "approval_required": spec.side_effect_class not in SAFE_SIDE_EFFECT_CLASSES,
        }
        for spec in ToolRegistry().list_specs()
    ]
    return "\n\n".join([
        AGENT_CONVERSATION_SYSTEM_PROMPT,
        AGENT_MARKDOWN_RESPONSE_PROMPT,
        AGENT_TOOL_PROTOCOL_PROMPT.replace("{tools}", json.dumps(tools, ensure_ascii=False)),
    ])


def _tool_call_summary(call: AgentToolCall) -> dict[str, Any]:
    return {
        "tool_call_id": call.tool_call_id,
        "tool_name": call.tool_name,
        "status": call.status,
        "approval_required": call.approval_required,
        "error_code": call.error_code,
    }


def _tool_result_message(call: AgentToolCall) -> str:
    payload = {
        "tool_call_id": call.tool_call_id,
        "tool_name": call.tool_name,
        "status": call.status,
        "approval_required": call.approval_required,
        "output": call.output_json_redacted,
        "error_code": call.error_code,
        "error_message": call.error_message,
    }
    return (
        "工具执行结果如下。请根据这个结果继续完成用户请求；"
        "如果工具失败，请直接说明失败原因和下一步建议，不要再次声明已经执行成功。\n"
        f"{json.dumps(payload, ensure_ascii=False, default=str)}"
    )


def _format_memory_context(candidates: list[MemoryCandidate]) -> str:
    lines = [
        "项目记忆上下文（用于辅助理解当前请求，不等同于实时证据；涉及高风险工具或副作用时仍需 EvidenceRef/审批/工具结果确认）："
    ]
    for index, candidate in enumerate(candidates, start=1):
        content = " ".join(candidate.content.split())
        if len(content) > 500:
            content = f"{content[:500]}..."
        lines.append(
            (
                f"{index}. memory_id={candidate.memory_id}, version={candidate.memory_version}, "
                f"profile={candidate.retrieval_profile}, score={candidate.retrieval_score:.4f}, "
                f"confidence={candidate.confidence:.2f}, stale_score={candidate.stale_score:.2f}, "
                f"title={candidate.title}\n"
                f"   content={content}"
            )
        )
    return "\n".join(lines)


def _format_run_context(run: AgentRun) -> str:
    return (
        "当前 Agent Run 上下文：\n"
        f"- run_id={run.run_id}\n"
        f"- project_id={run.project_id}\n"
        f"- conversation_id={run.conversation_id or ''}\n"
        f"- max_iterations={run.max_iterations}\n"
        "工具调用规则：如果工具 input schema 需要 project_id，直接使用当前 project_id，"
        "不要向用户反问 project_id。用户要求创建、生成或组合测试场景时，优先调用 scenario.compose_draft；"
        "但调用 scenario.compose_draft 前必须先调用 testcase.query_project_cases 获取当前项目候选用例。"
        "如缺少 environment_id，可先调用 project.read_context 获取默认环境。"
    )


def _should_hold_for_tool_request_detection(content: str) -> bool:
    stripped = content.lstrip()
    if not stripped:
        return True
    if "```agent_tool_request".startswith(stripped):
        return True
    if stripped.startswith("```agent_tool_request"):
        return True
    if "{".startswith(stripped) or stripped.startswith("{"):
        return True
    return False


def _looks_like_tool_request_content(content: str) -> bool:
    stripped = content.strip()
    return stripped.startswith("```agent_tool_request") or (
        stripped.startswith("{")
        and stripped.endswith("}")
        and '"tool_name"' in stripped
    )


def _normalize_agent_markdown_response(content: str) -> str:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    normalized = _normalize_inline_markdown_tables(normalized)
    normalized = _close_unclosed_markdown_fence(normalized)
    return "\n".join(line.rstrip() for line in normalized.splitlines()).strip()


def _normalize_inline_markdown_tables(content: str) -> str:
    lines: list[str] = []
    in_fence = False
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            lines.append(line.rstrip())
            in_fence = not in_fence
            continue
        if in_fence:
            lines.append(line.rstrip())
            continue
        normalized_table = _normalize_inline_markdown_table_line(line)
        if normalized_table is not None:
            lines.extend(normalized_table.split("\n"))
        else:
            lines.append(line.rstrip())
    return "\n".join(lines)


def _normalize_inline_markdown_table_line(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("|") or "----" not in stripped:
        return None
    cells = [cell.strip() for cell in stripped.split("|")]
    separator_start = -1
    separator_end = -1
    for index, cell in enumerate(cells):
        if not MARKDOWN_TABLE_SEPARATOR_CELL_RE.fullmatch(cell):
            continue
        end = index
        while end < len(cells) and MARKDOWN_TABLE_SEPARATOR_CELL_RE.fullmatch(cells[end]):
            end += 1
        if end - index >= 2:
            separator_start = index
            separator_end = end
            break
    if separator_start < 0:
        return None

    column_count = separator_end - separator_start
    before_separator = [cell for cell in cells[:separator_start] if cell]
    if len(before_separator) != column_count:
        return None
    after_separator = [cell for cell in cells[separator_end:] if cell]
    if after_separator and len(after_separator) % column_count != 0:
        return None

    header = before_separator
    separator = cells[separator_start:separator_end]
    rows = [
        after_separator[index:index + column_count]
        for index in range(0, len(after_separator), column_count)
    ]
    return "\n".join(
        [
            _format_markdown_table_row(header),
            _format_markdown_table_separator(separator),
            *[_format_markdown_table_row(row) for row in rows],
        ]
    )


def _format_markdown_table_row(cells: list[str]) -> str:
    normalized_cells = [_normalize_markdown_table_cell(cell) for cell in cells]
    return "| " + " | ".join(normalized_cells) + " |"


def _format_markdown_table_separator(cells: list[str]) -> str:
    normalized_cells = []
    for cell in cells:
        left_aligned = cell.startswith(":")
        right_aligned = cell.endswith(":")
        if left_aligned and right_aligned:
            normalized_cells.append(":---:")
        elif left_aligned:
            normalized_cells.append(":---")
        elif right_aligned:
            normalized_cells.append("---:")
        else:
            normalized_cells.append("---")
    return "| " + " | ".join(normalized_cells) + " |"


def _normalize_markdown_table_cell(cell: str) -> str:
    normalized = " ".join(cell.split())
    return normalized if normalized else "-"


def _close_unclosed_markdown_fence(content: str) -> str:
    fence_count = sum(1 for line in content.splitlines() if line.strip().startswith("```"))
    if fence_count % 2 == 0:
        return content
    return f"{content}\n```"


def _assistant_message_from_run(run: AgentRun) -> str | None:
    if not isinstance(run.result_json, dict):
        return None
    message = run.result_json.get("message")
    if isinstance(message, str) and message.strip():
        return message
    return None


def _http_exception_detail(exc: HTTPException) -> str:
    if isinstance(exc.detail, str):
        return exc.detail
    return json.dumps(exc.detail, ensure_ascii=False, default=str)


def _conversation_title(intent: str) -> str:
    normalized = " ".join(intent.split())
    return normalized[:60] if normalized else "未命名会话"


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
